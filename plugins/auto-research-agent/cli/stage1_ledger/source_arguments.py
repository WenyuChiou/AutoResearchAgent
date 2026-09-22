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
    "netrc",
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
_HEADER_NAME = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
# These fields carry public navigation or status values in the Stage 1
# contracts. Keep the allowlist narrow: every other compound ending in
# ``token`` or ``key`` is treated as credential-bearing.
_PUBLIC_FIELD_NAMES = {
    "authenticationstatus",
    "authorizationstatus",
    "maxtokens",
    "pagetoken",
    "publickey",
    "sortkey",
    "sortkeys",
}
_ARGV_HEADER_FLAGS = {"h", "header", "headers", "proxyheader"}
_ARGV_PRIVATE_FLAGS = {
    "b",
    "c",
    "cookie",
    "cookiejar",
    "n",
    "netrc",
    "netrcfile",
    "oauth2bearer",
    "proxyuser",
    "u",
    "user",
}
# These short words are public in compounds such as page_token or sort_key.
# Known multiword names still match when followed by a carrier suffix.
_PRIVATE_COMPONENTS = (_NAMES | set(_SUFFIXES)) - {"key", "token", "sig"}
_MAX_COMPONENT_NAME = max(map(len, _PRIVATE_COMPONENTS))


def _normalized(name):
    if not isinstance(name, str):
        return ""
    # Normalize before decoding too, so full-width percent escapes are visible.
    return unicodedata.normalize("NFKC", unquote(unicodedata.normalize("NFKC", name)))


def _segments(name):
    normalized = _normalized(name)
    normalized = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", normalized)
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", normalized)
    return re.findall(r"[\w-]+", normalized.casefold())


def _name(name):
    return "".join(c for c in _normalized(name).casefold() if c.isalnum())


def _words(name):
    normalized = _normalized(name)
    normalized = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", normalized)
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", normalized)
    return re.findall(r"[^\W_]+", normalized.casefold())


def _sensitive(name):
    for segment in _segments(name):
        normalized = _name(segment)
        if normalized in _PUBLIC_FIELD_NAMES:
            continue
        if normalized in _NAMES or normalized.endswith(_SUFFIXES):
            return True
        words = _words(segment)
        if any(
            word in {"key", "keys", "secret", "secrets", "token", "tokens"}
            for word in words
        ):
            return True
        parts = [part for part in re.split(r"[_-]+", segment) if part]
        for start in range(len(parts)):
            candidate = ""
            for index in range(start, len(parts)):
                candidate += parts[index]
                if len(candidate) > _MAX_COMPONENT_NAME:
                    break
                if candidate in _PRIVATE_COMPONENTS:
                    return True
    return False


def _field_sensitive(name, path):
    normalized = _name(name)
    if normalized in _PUBLIC_FIELD_NAMES:
        return False
    if normalized in {"key", "keys"} and path and path[-1] == "sort":
        return False
    return _sensitive(name)


def _label(value):
    # A header/argv item can include a value. Only its label is a field name.
    normalized = _normalized(value)
    assignment = _ASSIGNMENT.match(normalized)
    return assignment[1] if assignment else normalized


def _reject():
    # This error also reaches CLI output and validator reports. Never echo input.
    raise LedgerError("source-credentials-forbidden")


def _check_argv(items):
    for index, item in enumerate(items):
        if not isinstance(item, str):
            continue
        normalized = _normalized(item).strip()
        if not normalized.startswith("-"):
            continue
        single_dash = not normalized.startswith("--")
        option = normalized.lstrip("-")
        inline = None
        if (
            single_dash
            and len(option) > 1
            and option[0]
            in {
                "H",
                "U",
                "b",
                "c",
                "n",
                "u",
            }
        ):
            option, inline = option[0], option[1:]
        elif "=" in option:
            option, inline = option.split("=", 1)
        option_name = _name(option)
        if _sensitive(option):
            _reject()
        if option_name in _ARGV_PRIVATE_FLAGS:
            _reject()
        if option_name in _ARGV_HEADER_FLAGS:
            supplied = inline
            if supplied is None and index + 1 < len(items):
                supplied = items[index + 1]
            if isinstance(supplied, str) and _sensitive(_label(supplied)):
                _reject()


def _text(value):
    for line in value.splitlines():
        assignment = _ASSIGNMENT.match(_normalized(line))
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


def _string_fields(value, path=()):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _string_fields(
                item, path + tuple(_name(s) for s in _segments(key))
            )
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _string_fields(item, path + (str(index),))
    elif isinstance(value, str):
        yield path, value


def _header_pair_value(path, fields):
    position = path[-1]
    if not position.isdecimal() or len(position) > 9 or int(position) % 2 != 1:
        return False
    labels = fields.get(path[:-1] + (str(int(position) - 1),), [])
    # Only an unambiguous preceding bare label establishes a name/value pair.
    # A complete header line is not a bare label; later lines stay checked.
    return len(labels) == 1 and _HEADER_NAME.fullmatch(labels[0]) is not None


def _arguments(value, path=(), fields=None):
    if fields is None:
        fields = {}
        for field, item in _string_fields(value):
            fields.setdefault(field, []).append(item)
    if isinstance(value, dict):
        if any(_field_sensitive(key, path) for key in value):
            _reject()
        # Header collections also commonly use {name: ..., value: ...} entries.
        named = {_name(key): item for key, item in value.items()}
        if "value" in named and _sensitive(named.get("name")):
            _reject()
        for key, item in value.items():
            _arguments(item, path + tuple(_name(s) for s in _segments(key)), fields)
    elif isinstance(value, list):
        if any(p in {"args", "arguments", "argv"} for p in path):
            _check_argv(value)
        for index, item in enumerate(value):
            _arguments(item, path + (str(index),), fields)
    elif isinstance(value, str):
        # Flattened scalar slots and name/value headers must keep their parent
        # context. Named header values are not labels (User-Agent: token is public).
        header_label = any(p in {"headers", "header"} for p in path) and (
            path[-1] in {"headers", "header", "name"}
            or (path[-1].isdigit() and not _header_pair_value(path, fields))
        )
        argument_label = any(p in {"args", "arguments", "argv"} for p in path) and (
            _normalized(value).startswith("-")
        )
        if header_label and _sensitive(_label(value)):
            _reject()
        if argument_label:
            argv = [value]
            if path[-1].isdigit():
                following = fields.get(path[:-1] + (str(int(path[-1]) + 1),), [])
                if len(following) == 1:
                    argv.extend(following)
            _check_argv(argv)
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
