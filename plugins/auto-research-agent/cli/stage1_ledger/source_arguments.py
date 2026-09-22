"""Reject credential-bearing source metadata; never rewrite or retain its values."""

import re
import unicodedata
from urllib.parse import parse_qsl, unquote, urlsplit

from .journal import LedgerError


_NAMES = {
    "auth",
    "authentication",
    "authorization",
    "proxyauthorization",
    "cookie",
    "cookies",
    "cookiejar",
    "setcookie",
    "key",
    "apikey",
    "token",
    "bearer",
    "password",
    "passwd",
    "pwd",
    "secret",
    "credential",
    "credentials",
    "signature",
    "sig",
    "privatekey",
    "accesskey",
    "accesskeyid",
    "subscriptionkey",
    "ocpapimsubscriptionkey",
    "oauth",
    "oauth2",
    "jwt",
    "httpauth",
    "passphrase",
    "clientassertion",
    "codeverifier",
    "sessionid",
}
_SUFFIXES = (
    "apikey",
    "accesstoken",
    "refreshtoken",
    "idtoken",
    "clientsecret",
    "password",
    "credential",
    "credentials",
    "signature",
    "securitytoken",
    "privatekey",
    "secretaccesskey",
    "accesskeyid",
    "subscriptionkey",
    "apitoken",
    "authtoken",
    "sessiontoken",
    "csrftoken",
    "xsrftoken",
    "bearertoken",
    "apisecret",
    "passphrase",
    "clientassertion",
    "codeverifier",
    "sessionid",
)
_ASSIGNMENT = re.compile(r"^\s*(?:--)?([^\s:=]+)\s*[:=]")


def _name(name):
    if not isinstance(name, str):
        return ""
    normalized = unicodedata.normalize("NFKC", unquote(name)).casefold()
    return "".join(c for c in normalized if c.isalnum())


def _sensitive(name):
    normalized = _name(name)
    return normalized in _NAMES or normalized.endswith(_SUFFIXES)


def _reject():
    # This error also reaches CLI output and validator reports. Never echo input.
    raise LedgerError("source-credentials-forbidden")


def _text(value):
    for line in value.splitlines():
        assignment = _ASSIGNMENT.match(line)
        if assignment and _sensitive(assignment[1]):
            _reject()
    if not any(marker in value for marker in (":", "?", "#")) and not value.startswith(
        "//"
    ):
        return
    try:
        uri = urlsplit(value)
    except ValueError:
        raise LedgerError("source-public-uri-invalid") from None
    if "@" in unquote(uri.netloc):
        _reject()
    if uri.scheme.lower() in {"http", "https"} and not uri.netloc:
        if "@" in unquote(uri.path.lstrip("/").split("/")[0]):
            _reject()
    for part in (uri.query, uri.fragment, uri.fragment.split("?", 1)[-1]):
        # Fragment routes can contain OAuth callback arguments; some readers
        # also recognize semicolons as query separators. Reserve URI `code` as
        # an authorization-code field; ordinary JSON params.code stays public.
        for key, item in parse_qsl(part.replace(";", "&"), keep_blank_values=True):
            if _sensitive(key) or _name(key) == "code":
                _reject()
            # Redirect/return URLs can themselves contain credential arguments.
            _text(item)


def _arguments(value, field=""):
    if isinstance(value, dict):
        if any(_sensitive(key) for key in value):
            _reject()
        # Header collections also commonly use {name: ..., value: ...} entries.
        fields = {_name(key): item for key, item in value.items()}
        if "value" in fields and _sensitive(fields.get("name")):
            _reject()
        for key, item in value.items():
            _arguments(item, _name(key))
    elif isinstance(value, list):
        for item in value:
            if (
                isinstance(item, str)
                and (
                    field in {"headers", "header"}
                    or (
                        field in {"args", "arguments", "argv"} and item.startswith("--")
                    )
                )
                and _sensitive(item)
            ):
                _reject()
            _arguments(item, field)
    elif isinstance(value, str):
        _text(value)


def check_source_arguments(payload):
    """Shared write/replay boundary, before schema diagnostics can echo input."""
    kind = payload.get("kind")
    if kind in {"SourceReadStarted", "SourceImportStarted"}:
        _arguments(payload.get("source_uri"))
    if kind == "SourceReadStarted":
        _arguments(payload.get("request"))
    if kind == "SourceReadFinished":
        _arguments(payload.get("resolved_uri"))
