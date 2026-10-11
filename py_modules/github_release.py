"""Bounded public GitHub release metadata fallback when the API is rate limited."""
from html.parser import HTMLParser
import re
import ssl
import urllib.parse
import urllib.request


REPO = 'lonewolf0622/HelixSR'
ROOT = f'https://github.com/{REPO}'
LATEST = ROOT + '/releases/latest'
MAX_HTML_BYTES = 2 << 20
MAX_RELEASE_BYTES = 512 << 20
VERSION = re.compile(r'v?(\d+)\.(\d+)\.(\d+)\Z')
DIGEST = re.compile(r'sha256:([a-fA-F0-9]{64})\Z')


def _parts(url):
    parts = urllib.parse.urlsplit(url)
    if (parts.scheme != 'https' or parts.username or parts.password or parts.port is not None
            or not parts.hostname or parts.fragment or parts.netloc.lower() != parts.hostname):
        raise ValueError('Unexpected upstream release URL')
    return parts


def _tag_page(url):
    parts = _parts(url)
    prefix = f'/{REPO}/releases/tag/'
    return (parts.hostname == 'github.com' and not parts.query
            and parts.path.startswith(prefix)
            and bool(VERSION.fullmatch(parts.path[len(prefix):])))


def _expanded(url, expected):
    parts = _parts(url)
    return parts.hostname == 'github.com' and not parts.query and parts.path == expected


def _asset_target(url, expected):
    parts = _parts(url)
    if parts.hostname == 'github.com':
        return not parts.query and parts.path == urllib.parse.urlsplit(expected).path
    return parts.hostname == 'release-assets.githubusercontent.com' and parts.path.startswith('/')


class _Redirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed):
        self.allowed = allowed
        self.hops = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.hops += 1
        if self.hops > 3 or not self.allowed(newurl):
            raise ValueError('Unexpected upstream release redirect')
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if req.get_method() == 'HEAD':
            # urllib's default redirect_request silently changes HEAD to GET.
            # Keep asset metadata checks header-only across GitHub's CDN hop.
            redirected.method = 'HEAD'
        return redirected


def _open(url, *, method, context, allowed):
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=context), _Redirect(allowed))
    response = opener.open(urllib.request.Request(
        url, headers={'User-Agent': 'HelixSR-Decky/0.1', 'Accept': 'text/html'},
        method=method), timeout=20)
    if not allowed(response.geturl()):
        response.close()
        raise ValueError('Unexpected upstream release destination')
    return response


class _AssetRows(HTMLParser):
    def __init__(self, href):
        super().__init__(convert_charrefs=True)
        self.href = href
        self.depth = 0
        self.links = []
        self.digests = []
        self.matches = []

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if tag == 'li':
            if self.depth:
                self.depth += 1
            elif 'Box-row' in data.get('class', '').split():
                self.depth = 1
                self.links = []
                self.digests = []
        elif self.depth and tag == 'a':
            self.links.append(data.get('href'))
        elif self.depth and tag == 'clipboard-copy':
            self.digests.append(data.get('value'))

    def handle_endtag(self, tag):
        if tag != 'li' or not self.depth:
            return
        self.depth -= 1
        if not self.depth and self.href in self.links:
            if self.links.count(self.href) != 1 or len(self.digests) != 1:
                raise ValueError('Ambiguous official release asset row')
            digest = self.digests[0]
            if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
                raise ValueError('Official asset row lacks a SHA256 digest')
            self.matches.append(DIGEST.fullmatch(digest).group(1).lower())

    def digest(self):
        if self.depth or len(self.matches) != 1:
            raise ValueError('Official release asset or digest is missing or duplicated')
        return self.matches[0]


def web_latest_release(context=None):
    """Read the official latest tag, exact asset digest, and exact HEAD byte size."""
    context = context if context is not None else ssl.create_default_context()
    with _open(LATEST, method='GET', context=context,
               allowed=lambda url: url == LATEST or _tag_page(url)) as response:
        page = response.geturl()
        if not _tag_page(page):
            raise ValueError('Latest release did not resolve to a stable tag')
        # Read only a byte to complete this request. The redirect is the authority.
        response.read(1)
    tag = page.rsplit('/', 1)[1]
    version = tag.removeprefix('v')
    asset_href = f'/{REPO}/releases/download/{tag}/HelixSR-{version}.zip'
    asset = 'https://github.com' + asset_href
    expanded_path = f'/{REPO}/releases/expanded_assets/{tag}'
    expanded = 'https://github.com' + expanded_path
    with _open(expanded, method='GET', context=context,
               allowed=lambda url: _expanded(url, expanded_path)) as response:
        raw = response.read(MAX_HTML_BYTES + 1)
        if len(raw) > MAX_HTML_BYTES:
            raise ValueError('Upstream release assets page is too large')
    parser = _AssetRows(asset_href)
    parser.feed(raw.decode('utf-8'))
    parser.close()
    digest = parser.digest()
    with _open(asset, method='HEAD', context=context,
               allowed=lambda url: _asset_target(url, asset)) as response:
        raw_size = response.headers.get('Content-Length')
        if not isinstance(raw_size, str) or not re.fullmatch(r'[0-9]+', raw_size):
            raise ValueError('Official asset lacks exact Content-Length')
        size = int(raw_size)
        if not 0 < size <= MAX_RELEASE_BYTES:
            raise ValueError('Official asset size is outside the allowed range')
    return dict(version=version, url=asset, sha256=digest, size=size, page=page)
