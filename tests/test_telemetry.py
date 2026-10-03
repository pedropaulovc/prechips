"""Telemetry's exported trace/log semantics and offline console contract."""

import atexit
import io
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace

import grpc
import pytest
from opentelemetry.proto.collector.logs.v1 import logs_service_pb2, logs_service_pb2_grpc
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2, trace_service_pb2_grpc
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from prechips import __version__, telemetry


@pytest.fixture(autouse=True)
def isolated_telemetry(monkeypatch):
    # No developer collector credentials or parent trace may leak into a test.
    for name in tuple(telemetry.os.environ):
        if name.startswith("OTEL_") or name in {"TRACEPARENT", "TRACESTATE", "NO_COLOR"}:
            monkeypatch.delenv(name)
    monkeypatch.setattr(telemetry, "_telemetry", None)
    yield
    if telemetry._telemetry is not None:
        telemetry._telemetry.flush()
        atexit.unregister(telemetry._telemetry.flush)


@pytest.fixture
def exporters(monkeypatch):
    spans = InMemorySpanExporter()
    logs = InMemoryLogRecordExporter()
    monkeypatch.setattr(
        telemetry, "_exporter", lambda signal: spans if signal == "traces" else logs
    )
    return spans, logs


def finding(status="error"):
    return SimpleNamespace(
        rule="sizing",
        subject="pivot_bore",
        status=status,
        numbers={"diameter_mm": 6.375, "low_mm": 6.5},
        cite=["fixture measurement"],
        sentence="Reamer is below the low limit.",
    )


def test_span_tree_and_correlated_findings(exporters):
    spans, logs = exporters
    assert telemetry.current() is None
    t = telemetry.configure("check")
    assert telemetry.configure("traveler") is t
    assert telemetry.current() is t
    with t.span("rule.sizing", subject="pivot_bore"):
        t.finding(finding())
    t.flush()
    t.flush()
    assert telemetry.current() is None
    root, child = sorted(spans.get_finished_spans(), key=lambda span: span.start_time)
    assert root.name == "prechips.check"
    assert root.parent is None
    assert child.name == "rule.sizing"
    assert child.parent.span_id == root.context.span_id
    assert child.context.trace_id == root.context.trace_id
    assert child.attributes["subject"] == "pivot_bore"
    assert child.attributes["status"] == "error"
    assert json.loads(child.attributes["numbers"]) == finding().numbers
    (exported,) = logs.get_finished_logs()
    record = exported.log_record
    assert record.trace_id == child.context.trace_id
    assert record.span_id == child.context.span_id
    assert record.body == "✗ Reamer is below the low limit."
    assert record.severity_text == "ERROR"
    assert record.attributes["rule"] == "sizing"
    assert record.attributes["cite"] == ("fixture measurement",)


def test_remote_parent_and_resource_routing(monkeypatch, exporters):
    spans, logs = exporters
    trace_id = "0123456789abcdef0123456789abcdef"
    parent_id = "0123456789abcdef"
    monkeypatch.setenv("TRACEPARENT", f"00-{trace_id}-{parent_id}-01")
    monkeypatch.setenv("TRACESTATE", "vendor=value")
    monkeypatch.setenv("OTEL_SERVICE_NAMESPACE", "harmonic-analyzer")
    monkeypatch.setenv("OTEL_RESOURCE_ATTRIBUTES", "shop=pedro,service.name=not-prechips")
    t = telemetry.configure("check")
    t.log("info", "Checking the bundle.")
    t.flush()
    (root,) = spans.get_finished_spans()
    assert root.context.trace_id == int(trace_id, 16)
    assert root.parent.span_id == int(parent_id, 16)
    assert root.parent.is_remote
    assert root.context.trace_state.to_header() == "vendor=value"
    assert root.resource.attributes["service.name"] == "prechips"
    assert root.resource.attributes["service.version"] == __version__
    assert root.resource.attributes["service.namespace"] == "harmonic-analyzer"
    assert root.resource.attributes["shop"] == "pedro"
    assert logs.get_finished_logs()[0].resource == root.resource


def test_raised_exception_marks_child_error(exporters):
    spans, _ = exporters
    t = telemetry.configure("check")
    with pytest.raises(ValueError, match="bad dimensions"), t.span("rule.sizing"):
        raise ValueError("bad dimensions")
    t.flush()
    child = next(span for span in spans.get_finished_spans() if span.name == "rule.sizing")
    assert child.status.status_code is StatusCode.ERROR
    (event,) = child.events
    assert event.name == "exception"
    assert event.attributes["exception.type"] == "ValueError"
    assert event.attributes["exception.message"] == "bad dimensions"


@pytest.mark.parametrize(
    ("status", "severity", "glyph"),
    [
        ("error", "ERROR", "✗ "),
        ("warn", "WARN", "! "),
        ("unknown", "WARN", "? "),
        ("unsupported", "WARN", "? "),
        ("info", "INFO", ""),
        ("pass", "DEBUG", ""),
        ("not_applicable", "DEBUG", ""),
    ],
)
def test_finding_status_semantics(status, severity, glyph, exporters):
    _, logs = exporters
    t = telemetry.configure("check")
    t.finding(finding(status))
    t.flush()
    (exported,) = logs.get_finished_logs()
    assert exported.log_record.severity_text == severity
    assert exported.log_record.body == glyph + finding().sentence
    assert exported.log_record.attributes["status"] == status


def test_no_endpoint_means_no_exporter_or_warning(capsys):
    assert telemetry._exporter("traces") is None
    assert telemetry._exporter("logs") is None
    t = telemetry.configure("check")
    t.flush()
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize(
    ("variable", "value"),
    [("OTEL_EXPORTER_OTLP_LOGS_PROTOCOL", "http/json"), ("OTEL_EXPORTER_OTLP_LOGS_TIMEOUT", "5s")],
)
def test_malformed_export_setting_warns_once_and_exports_nothing(
    variable, value, monkeypatch, capsys
):
    received = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(self.path)
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # Traces alone are well formed; one malformed signal still disables all export.
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", f"http://127.0.0.1:{server.server_port}")
        monkeypatch.setenv(variable, value)
        t = telemetry.configure("check")
        with t.span("rule.sizing"):
            t.finding(finding("unknown"))
        t.flush()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert received == []
    assert capsys.readouterr().err.count(variable) == 1


def test_no_color_preserves_glyphs_without_ansi(monkeypatch):
    class Tty(io.StringIO):
        def isatty(self):
            return True

    stderr = Tty()
    monkeypatch.setattr(telemetry.sys, "stderr", stderr)
    monkeypatch.setenv("NO_COLOR", "1")
    handler = telemetry.console_handler(False)
    record = logging.LogRecord("prechips", logging.WARNING, "", 0, "? Check headroom.", (), None)
    record.status = "unknown"
    handler.handle(record)
    assert stderr.getvalue() == "? Check headroom.\n"
    assert "\x1b" not in stderr.getvalue()


def test_verbose_shows_clean_findings_and_default_hides_them(monkeypatch):
    stderr = io.StringIO()
    monkeypatch.setattr(telemetry.sys, "stderr", stderr)
    record = logging.LogRecord("prechips", logging.DEBUG, "", 0, "Tool fits.", (), None)
    record.status, record.rule, record.subject = "pass", "sizing", "pivot_bore"
    telemetry.console_handler(False).emit(record)
    assert stderr.getvalue() == ""
    telemetry.console_handler(True).handle(record)
    assert "sizing" in stderr.getvalue()
    assert "pivot_bore" in stderr.getvalue()
    assert "Tool fits." in stderr.getvalue()


@pytest.mark.parametrize("protocol", ["http/protobuf", "grpc"])
def test_real_otlp_transports_preserve_finding_context(protocol, monkeypatch):
    """A loopback collector observes actual encoded spans/logs and env headers."""
    received = {}
    if protocol == "http/protobuf":

        class Receiver(BaseHTTPRequestHandler):
            def do_POST(self):
                signal = self.path.removeprefix("/v1/")
                cls = (
                    trace_service_pb2.ExportTraceServiceRequest
                    if signal == "traces"
                    else logs_service_pb2.ExportLogsServiceRequest
                )
                received[signal] = (
                    cls.FromString(self.rfile.read(int(self.headers["Content-Length"]))),
                    self.headers["shop"],
                )
                self.send_response(200)
                self.send_header("Content-Type", "application/x-protobuf")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        endpoint = f"http://127.0.0.1:{server.server_port}"
    else:

        class TraceReceiver(trace_service_pb2_grpc.TraceServiceServicer):
            def Export(self, request, context):
                received["traces"] = (request, dict(context.invocation_metadata())["shop"])
                return trace_service_pb2.ExportTraceServiceResponse()

        class LogReceiver(logs_service_pb2_grpc.LogsServiceServicer):
            def Export(self, request, context):
                received["logs"] = (request, dict(context.invocation_metadata())["shop"])
                return logs_service_pb2.ExportLogsServiceResponse()

        pool = ThreadPoolExecutor(max_workers=2)
        server = grpc.server(pool)
        trace_service_pb2_grpc.add_TraceServiceServicer_to_server(TraceReceiver(), server)
        logs_service_pb2_grpc.add_LogsServiceServicer_to_server(LogReceiver(), server)
        port = server.add_insecure_port("127.0.0.1:0")
        server.start()
        endpoint = f"http://127.0.0.1:{port}"
    try:
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", endpoint)
        # Both per-signal protocol settings must beat the common setting.
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_PROTOCOL", "invalid-overridden")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_PROTOCOL", protocol)
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_LOGS_PROTOCOL", protocol)
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_HEADERS", "shop=pedro")
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_TIMEOUT", "1000")
        t = telemetry.configure("check")
        with t.span("rule.sizing"):
            t.finding(finding("unknown"))
        t.flush()
        trace_request, trace_shop = received["traces"]
        log_request, log_shop = received["logs"]
        spans = trace_request.resource_spans[0].scope_spans[0].spans
        child = next(span for span in spans if span.name == "rule.sizing")
        root = next(span for span in spans if span.name == "prechips.check")
        log = log_request.resource_logs[0].scope_logs[0].log_records[0]
        assert trace_shop == log_shop == "pedro"
        assert child.parent_span_id == root.span_id
        assert log.trace_id == root.trace_id == child.trace_id
        assert log.span_id == child.span_id
        assert log.body.string_value == "? Reamer is below the low limit."
    finally:
        if protocol == "http/protobuf":
            server.shutdown()
            server.server_close()
            thread.join()
        else:
            server.stop(0).wait()
            pool.shutdown()
