"""STEP (ISO 10303-21) face references for the prechips geometry kernel.

Standard library only: this module is imported both by the host test-suite and
by ``freecad_job.py`` inside ``freecadcmd``.

A face reference is the consumer's export form (harmonic-analyzer
``_export_feature_faces.face_ref``)::

    #<entity>/ADVANCED_FACE[<ordinal>]/<label>

``entity`` is the instance id, ``ordinal`` the 1-based file-order position among
simple ``ADVANCED_FACE`` records, ``label`` the raw first string argument with
doubled quotes undone.  All three must agree with the exact STEP bytes.  The
reference names a STEP entity, never a position in an imported face list:
:func:`StepFile.isolate_face` rewrites the file so a kernel reader transfers that
one face, in the same representation chain and units as the full import, and the
kernel matches its geometry against the full import's faces.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

REF_PATTERN = re.compile(r"#(\d+)/ADVANCED_FACE\[(\d+)\]/(.*)", re.DOTALL)

# Entities that hold a solid's/shell's faces, and the wrappers between a shell
# and the representation item that a shape representation lists.
_SHELLS = frozenset({"CLOSED_SHELL", "OPEN_SHELL"})
_SHELL_WRAPPERS = frozenset({"ORIENTED_CLOSED_SHELL", "ORIENTED_OPEN_SHELL"})
_ITEMS = frozenset(
    {"MANIFOLD_SOLID_BREP", "BREP_WITH_VOIDS", "SHELL_BASED_SURFACE_MODEL", "FACETED_BREP"}
)


class StepError(ValueError):
    """The STEP text cannot be parsed as an ISO 10303-21 exchange structure."""


class FaceRefError(ValueError):
    """A face reference does not name an ADVANCED_FACE of this exact STEP."""


@dataclass(frozen=True)
class StepFace:
    entity: int
    ordinal: int
    label: str

    @property
    def ref(self) -> str:
        return face_ref(self.entity, self.ordinal, self.label)


@dataclass(frozen=True)
class _Record:
    entity: int
    types: tuple[str, ...]  # one name, or every partial type of a complex instance
    body: str  # text after "=" up to (excluding) the terminating ";"
    refs: tuple[int, ...]  # referenced instance ids, outside strings, in order


def face_ref(entity: int, ordinal: int, label: str) -> str:
    return f"#{entity}/ADVANCED_FACE[{ordinal}]/{label}"


def parse_ref(ref: str) -> tuple[int, int, str]:
    """Split a reference; raise :class:`FaceRefError` naming it when malformed."""
    if not isinstance(ref, str):
        raise FaceRefError(f"{ref!r}: face reference is not a string")
    match = REF_PATTERN.fullmatch(ref)
    if match is None:
        raise FaceRefError(f"{ref}: not of the form #<entity>/ADVANCED_FACE[<ordinal>]/<label>")
    entity, ordinal = int(match.group(1)), int(match.group(2))
    if entity < 1 or ordinal < 1:
        raise FaceRefError(f"{ref}: entity id and ordinal must be positive")
    return entity, ordinal, match.group(3)


_STRING = r"'(?:[^']|'')*'"
_COMMENT_SCAN = re.compile(rf"{_STRING}|/\*.*?\*/|'|/\*", re.DOTALL)
_RECORD_SCAN = re.compile(rf"{_STRING}|'|[();]")


def _strip_comments(text: str) -> str:
    """Remove ``/* */`` comments outside strings."""
    out: list[str] = []
    last = 0
    for match in _COMMENT_SCAN.finditer(text):
        token = match.group(0)
        if token == "'":
            raise StepError("unterminated string")
        if token == "/*":
            raise StepError("unterminated comment")
        if token.startswith("/*"):
            out.append(text[last : match.start()])
            last = match.end()
    out.append(text[last:])
    return "".join(out)


def _split_records(data: str) -> list[str]:
    """Split a DATA section body into instance texts at top-level ``;``."""
    records: list[str] = []
    start, depth = 0, 0
    for match in _RECORD_SCAN.finditer(data):
        token = match.group(0)
        if token == "'":
            raise StepError("unterminated string")
        if token == "(":
            depth += 1
        elif token == ")":
            depth -= 1
            if depth < 0:
                raise StepError("unbalanced parentheses in DATA section")
        elif token == ";" and depth == 0:
            chunk = data[start : match.start()].strip()
            if chunk:
                records.append(chunk)
            start = match.end()
    if data[start:].strip():
        raise StepError("DATA section ends inside an instance")
    return records


_INSTANCE = re.compile(r"#(\d+)\s*=\s*(.*)", re.DOTALL)
_TYPE_AT = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_REF = re.compile(r"#(\d+)")


def _outside_strings(text: str) -> str:
    return re.sub(r"'(?:[^']|'')*'", "''", text)


def _complex_types(body: str) -> tuple[str, ...]:
    """Partial type names of ``( A(...) B(...) )`` at nesting depth one."""
    inner = _outside_strings(body)[1:]
    names: list[str] = []
    depth = 0
    token = ""
    for ch in inner:
        if ch == "(":
            if depth == 0 and token.strip():
                names.append(token.strip().upper())
            token = ""
            depth += 1
        elif ch == ")":
            depth -= 1
            token = ""
        elif depth == 0:
            token += ch
    return tuple(names)


def _first_string(body: str) -> str | None:
    match = re.match(r"\s*[A-Za-z_][A-Za-z0-9_]*\s*\(\s*'((?:[^']|'')*)'", body, re.DOTALL)
    return None if match is None else match.group(1).replace("''", "'")


def _is_shape_representation(name: str) -> bool:
    """A representation that lists geometric items (not a relationship or a
    presentation/styling representation)."""
    return (
        name.endswith("REPRESENTATION")
        and "PRESENTATION_REPRESENTATION" not in name
        and not name.startswith("PRESENTATION")
    )


class StepFile:
    """Parsed instance graph of one STEP file's DATA section."""

    def __init__(self, text: str) -> None:
        clean = _strip_comments(text)
        head = re.search(r"\bDATA\s*(\([^;]*\))?\s*;", clean)
        if head is None:
            raise StepError("no DATA section")
        end = re.search(r"\bENDSEC\s*;", clean[head.end() :])
        if end is None:
            raise StepError("DATA section has no ENDSEC")
        self._prefix = clean[: head.end()]
        self._suffix = clean[head.end() + end.start() :]
        self.records: dict[int, _Record] = {}
        self._order: list[int] = []
        faces: list[StepFace] = []
        for chunk in _split_records(clean[head.end() : head.end() + end.start()]):
            match = _INSTANCE.fullmatch(chunk)
            if match is None:
                raise StepError(f"malformed instance: {chunk[:60]!r}")
            entity, body = int(match.group(1)), match.group(2).strip()
            if entity in self.records:
                raise StepError(f"duplicate instance id #{entity}")
            if body.startswith("("):
                types = _complex_types(body)
            else:
                simple = _TYPE_AT.match(body)
                if simple is None:
                    raise StepError(f"#{entity}: instance has no type name")
                types = (simple.group(1).upper(),)
            refs = tuple(int(r) for r in _REF.findall(_outside_strings(body)))
            self.records[entity] = _Record(entity, types, body, refs)
            self._order.append(entity)
            if types == ("ADVANCED_FACE",):
                label = _first_string(body)
                if label is None:
                    raise StepError(f"#{entity}: ADVANCED_FACE has no label string")
                faces.append(StepFace(entity, len(faces) + 1, label))
        self.faces: tuple[StepFace, ...] = tuple(faces)
        self._face_by_entity = {face.entity: face for face in faces}
        users: dict[int, list[int]] = {}
        for record in self.records.values():
            for target in record.refs:
                users.setdefault(target, []).append(record.entity)
        self._users = users

    def resolve(self, ref: str) -> StepFace:
        """The ADVANCED_FACE ``ref`` names, or :class:`FaceRefError` naming ``ref``."""
        entity, ordinal, label = parse_ref(ref)
        record = self.records.get(entity)
        if record is None:
            raise FaceRefError(f"{ref}: STEP has no instance #{entity}")
        face = self._face_by_entity.get(entity)
        if face is None:
            raise FaceRefError(f"{ref}: #{entity} is {'/'.join(record.types)}, not ADVANCED_FACE")
        if face.ordinal != ordinal:
            raise FaceRefError(
                f"{ref}: #{entity} is ADVANCED_FACE ordinal {face.ordinal}, not {ordinal}"
            )
        if face.label != label:
            raise FaceRefError(f"{ref}: #{entity} carries label {face.label!r}, not {label!r}")
        return face

    def _has_type(self, entity: int, names: frozenset[str]) -> bool:
        record = self.records.get(entity)
        return record is not None and any(name in names for name in record.types)

    def isolate_face(self, entity: int) -> str:
        """STEP text whose shape representation(s) carry only ``entity``.

        Every instance is kept, so product structure, placements and units are
        those of the full file.  A new ``OPEN_SHELL`` holding the face, wrapped
        in a ``SHELL_BASED_SURFACE_MODEL``, replaces each representation item
        (solid or surface model) whose shell uses the face; nothing else
        references the original solid, so a reader transfers the one face.
        """
        if entity not in self._face_by_entity:
            raise FaceRefError(f"#{entity} is not an ADVANCED_FACE")
        holders = {entity}
        for user in self._users.get(entity, ()):
            if self._has_type(user, frozenset({"ORIENTED_FACE"})):
                holders.add(user)
        shells = {
            user
            for holder in holders
            for user in self._users.get(holder, ())
            if self._has_type(user, _SHELLS)
        }
        if not shells:
            raise FaceRefError(f"#{entity} is not used by any shell")
        wrapped = set(shells)
        for shell in shells:
            for user in self._users.get(shell, ()):
                if self._has_type(user, _SHELL_WRAPPERS):
                    wrapped.add(user)
        items = {
            user
            for shell in wrapped
            for user in self._users.get(shell, ())
            if self._has_type(user, _ITEMS)
        }
        if not items:
            raise FaceRefError(f"#{entity}: its shell is not a solid or surface-model item")
        reps = {
            user
            for item in items
            for user in self._users.get(item, ())
            if any(_is_shape_representation(name) for name in self.records[user].types)
        }
        if not reps:
            raise FaceRefError(f"#{entity}: its solid is not listed by a shape representation")
        top = max(self.records)
        shell_id, model_id = top + 1, top + 2
        pattern = re.compile("|".join(rf"#{item}(?!\d)" for item in sorted(items)))
        lines = []
        for record_id in self._order:
            body = self.records[record_id].body
            if record_id in reps:
                body = pattern.sub(f"#{model_id}", body)
            lines.append(f"#{record_id} = {body};")
        lines.append(f"#{shell_id} = OPEN_SHELL('',(#{entity}));")
        lines.append(f"#{model_id} = SHELL_BASED_SURFACE_MODEL('',(#{shell_id}));")
        return self._prefix + "\n" + "\n".join(lines) + "\n" + self._suffix
