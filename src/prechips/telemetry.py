"""Correlated OpenTelemetry records and their stderr rendering.

Only explicit standard OTLP endpoints enable export; an offline check has no
collector discovery, network traffic, or missing-collector warning.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import sys
from contextlib import contextmanager
from threading import Lock
from typing import Any

from opentelemetry import trace
from opentelemetry._logs import SeverityNumber
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from rich.console import Console
from rich.table import Table
from rich.text import Text
from rich.traceback import Traceback

from prechips import __version__

_GLYPHS = {"error": "✗", "warn": "!", "unknown": "?", "unsupported": "?"}
_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "success": logging.INFO,
    "warn": logging.WARNING,
    "error": logging.ERROR,
}
_STYLES = {logging.ERROR: "red", logging.WARNING: "yellow", logging.DEBUG: "dim"}
_telemetry: Telemetry | None = None
_configure_lock = Lock()
_RECORD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


class _OTelHandler(logging.Handler):
    """Bridge Python records using the supported OTel Logger.emit API."""

    def __init__(self, provider: LoggerProvider):
        super().__init__(logging.DEBUG)
        self.otel_logger = provider.get_logger("prechips", __version__)

    def emit(self, record: logging.LogRecord) -> None:
        attrs = {key: value for key, value in vars(record).items() if key not in _RECORD_FIELDS}
        severity = {
            logging.DEBUG: SeverityNumber.DEBUG,
            logging.INFO: SeverityNumber.INFO,
            logging.WARNING: SeverityNumber.WARN,
            logging.ERROR: SeverityNumber.ERROR,
            logging.CRITICAL: SeverityNumber.FATAL,
        }[record.levelno]
        self.otel_logger.emit(
            timestamp=int(record.created * 1_000_000_000),
            severity_number=severity,
            severity_text=severity.name,
            body=record.getMessage(),
            attributes=_attributes(attrs),
            exception=record.exc_info[1] if record.exc_info else None,
        )


def _attributes(attrs: dict[str, Any]) -> dict[str, Any]:
    """Keep structured evidence lossless without violating OTel attribute types."""
    result = {}
    for key, value in attrs.items():
        if isinstance(value, dict) or value is None:
            value = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
        elif isinstance(value, (list, tuple)):
            if all(isinstance(item, str) for item in value):
                value = tuple(value)
            else:
                value = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
        elif not isinstance(value, (str, bool, int, float)):
            value = str(value)
        result[key] = value
    return result


class _ConsoleHandler(logging.Handler):
    def __init__(self, verbose: bool):
        super().__init__(logging.DEBUG if verbose else logging.INFO)
        self.verbose = verbose
        self.console = Console(
            file=sys.stderr,
            force_terminal=bool(sys.stderr.isatty() and "NO_COLOR" not in os.environ),
            no_color="NO_COLOR" in os.environ or not sys.stderr.isatty(),
            highlight=False,
        )
        self._table_header = True

    def emit(self, record: logging.LogRecord) -> None:
        try:
            finding_status = getattr(record, "status", None)
            if finding_status and self.verbose:
                table = Table(show_header=self._table_header, box=None, padding=(0, 1))
                for label in ("Rule", "Subject", "Status", "Finding"):
                    table.add_column(label)
                table.add_row(
                    str(getattr(record, "rule", "")),
                    str(getattr(record, "subject", "")),
                    Text(str(finding_status), style=_STYLES.get(record.levelno, "green")),
                    Text(record.getMessage()),
                )
                self.console.print(table)
                self._table_header = False
            elif not finding_status or finding_status in _GLYPHS:
                self.console.print(Text(record.getMessage(), style=_STYLES.get(record.levelno, "")))
            if record.exc_info and record.exc_info[0] is not None:
                self.console.print(Traceback.from_exception(*record.exc_info, show_locals=True))
        except Exception:
            self.handleError(record)


def console_handler(verbose: bool) -> logging.Handler:
    """Render the same Python log records sent to the OTel log provider."""
    return _ConsoleHandler(verbose)


def _exporter(signal: str):
    """Resolve transport explicitly; let each SDK exporter resolve headers/TLS."""
    prefix = f"OTEL_EXPORTER_OTLP_{signal.upper()}"
    endpoint = os.environ.get(f"{prefix}_ENDPOINT", os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"))
    if not endpoint:
        return None
    protocol = (
        (
            os.environ.get(f"{prefix}_PROTOCOL")
            or os.environ.get("OTEL_EXPORTER_OTLP_PROTOCOL")
            or "http/protobuf"
        )
        .strip()
        .lower()
    )
    # The OTLP environment specifies milliseconds; Python exporter constructors
    # take seconds. Signal-specific settings override the common setting.
    timeout = os.environ.get(f"{prefix}_TIMEOUT") or os.environ.get("OTEL_EXPORTER_OTLP_TIMEOUT")
    kwargs = {"timeout": float(timeout) / 1000} if timeout else {}
    if protocol == "http/protobuf":
        if signal == "traces":
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            return OTLPSpanExporter(**kwargs)
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter

        return OTLPLogExporter(**kwargs)
    if protocol == "grpc":
        if signal == "traces":
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

            return OTLPSpanExporter(**kwargs)
        from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter

        return OTLPLogExporter(**kwargs)
    raise ValueError(f"Unsupported {prefix}_PROTOCOL: {protocol!r}")


class Telemetry:
    """One verb's root span, log pipeline, and idempotent exit-time cleanup."""

    def __init__(self, verb: str):
        resource_attrs = {"service.name": "prechips", "service.version": __version__}
        if namespace := os.environ.get("OTEL_SERVICE_NAMESPACE"):
            resource_attrs["service.namespace"] = namespace
        resource = Resource.create(resource_attrs)
        self.trace_provider = TracerProvider(resource=resource, shutdown_on_exit=False)
        self.log_provider = LoggerProvider(resource=resource, shutdown_on_exit=False)
        self._closed = False
        self._root_context = None
        self.logger = logging.getLogger("prechips")
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False
        self._handlers: list[logging.Handler] = []
        try:
            if exporter := _exporter("traces"):
                self.trace_provider.add_span_processor(BatchSpanProcessor(exporter))
            if exporter := _exporter("logs"):
                self.log_provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
            self.tracer = self.trace_provider.get_tracer("prechips", __version__)
            carrier = {
                key.lower(): os.environ[key]
                for key in ("TRACEPARENT", "TRACESTATE")
                if key in os.environ
            }
            parent = TraceContextTextMapPropagator().extract(carrier) if carrier else None
            self.root = self.tracer.start_span(f"prechips.{verb}", context=parent)
            self._root_context = trace.use_span(self.root, end_on_exit=True)
            self._root_context.__enter__()
            self._handlers = [
                _OTelHandler(self.log_provider),
                console_handler(False),
            ]
            for handler in self._handlers:
                self.logger.addHandler(handler)
        except BaseException:
            self.flush()
            raise

    @contextmanager
    def span(self, name: str, **attrs):
        """Start a current child; raised exceptions become ERROR span events."""
        with self.tracer.start_as_current_span(name, attributes=_attributes(attrs)) as span:
            yield span

    def log(self, severity: str, message: str, **attrs) -> None:
        """Send one Python record through both the OTel and console handlers."""
        self.logger.log(_LEVELS[severity], message, extra=_attributes(attrs))

    def finding(self, finding) -> None:
        """Correlate a finding to the active evaluation span and render its glyph."""
        status = getattr(finding.status, "value", finding.status)
        attrs = _attributes(
            {
                "rule": finding.rule,
                "subject": finding.subject,
                "status": status,
                "numbers": finding.numbers,
                "cite": finding.cite,
            }
        )
        trace.get_current_span().set_attributes(attrs)
        glyph = _GLYPHS.get(status)
        body = f"{glyph} {finding.sentence}" if glyph else finding.sentence
        severity = (
            "error"
            if status == "error"
            else "warn"
            if glyph
            else "info"
            if status == "info"
            else "debug"
        )
        self.log(severity, body, **attrs)

    def flush(self) -> None:
        """End the root, drain both batch queues, and shut down exactly once."""
        if self._closed:
            return
        self._closed = True
        try:
            if self._root_context is not None:
                self._root_context.__exit__(None, None, None)
        finally:
            try:
                self.trace_provider.force_flush()
            finally:
                try:
                    self.log_provider.force_flush()
                finally:
                    try:
                        self.trace_provider.shutdown()
                    finally:
                        self.log_provider.shutdown()
                        for handler in self._handlers:
                            self.logger.removeHandler(handler)
                            handler.close()


def configure(verb: str) -> Telemetry:
    """Configure once per process, continuing W3C context from the environment."""
    global _telemetry
    with _configure_lock:
        if _telemetry is None:
            _telemetry = Telemetry(verb)
            atexit.register(_telemetry.flush)
        return _telemetry
