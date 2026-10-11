"""The public fallback accepts only the exact official asset digest and byte size."""
import sys
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'py_modules'))
import github_release as release


TAG = 'v1.8.1'
PAGE = release.ROOT + '/releases/tag/' + TAG
EXPANDED = release.ROOT + '/releases/expanded_assets/' + TAG
HREF = f'/{release.REPO}/releases/download/{TAG}/HelixSR-1.8.1.zip'
ASSET = 'https://github.com' + HREF
CDN = 'https://release-assets.githubusercontent.com/github-production-release-asset/file?sp=signed'
DIGEST = '5b2d06db22d59aaa8c931fc06d3a8e354e65dde1bef9fce90086542f02d4a627'


def row(href=HREF, digest=DIGEST, *, copies=1):
    values = ''.join(f'<clipboard-copy value="sha256:{digest}"></clipboard-copy>'
                     for _ in range(copies))
    return (f'<li class="Box-row"><a href="{href}">HelixSR-1.8.1.zip</a>'
            f'{values}<span>54 MB</span></li>')


class Response:
    def __init__(self, url, body=b'', headers=None):
        self.url = url
        self.body = body if isinstance(body, bytes) else body.encode()
        self.headers = headers or {}
        self.read_sizes = []
        self.closed = False

    def geturl(self):
        return self.url

    def read(self, size=-1):
        self.read_sizes.append(size)
        return self.body[:size] if size >= 0 else self.body

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


class Opener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout):
        self.requests.append((request.full_url, request.get_method(), timeout))
        if not self.responses:
            raise AssertionError('Unexpected extra public request')
        return self.responses.pop(0)


class WebLatestReleaseTests(unittest.TestCase):
    def fetch(self, *, page=PAGE, html=None, expanded=EXPANDED,
              asset_final=CDN, head=None):
        responses = [Response(page, 'x'), Response(expanded, html if html is not None else row()),
                     Response(asset_final, headers=head if head is not None else {'Content-Length': '56650779'})]
        opener = Opener(responses)
        with patch.object(release.urllib.request, 'build_opener', return_value=opener):
            try:
                value = release.web_latest_release(context=object())
                return value, opener, responses
            finally:
                self.assertEqual(opener.requests[:len(responses) - len(opener.responses)],
                                 [(release.LATEST, 'GET', 20),
                                  (EXPANDED, 'GET', 20),
                                  (ASSET, 'HEAD', 20)][:len(opener.requests)])

    def test_exact_official_digest_and_live_head_size(self):
        value, opener, responses = self.fetch()
        self.assertEqual(value, dict(version='1.8.1', url=ASSET, sha256=DIGEST,
                                     size=56650779, page=PAGE))
        self.assertEqual(len(opener.requests), 3)
        self.assertEqual(responses[0].read_sizes, [1])
        self.assertEqual(responses[1].read_sizes, [release.MAX_HTML_BYTES + 1])
        self.assertEqual(responses[2].read_sizes, [])

    def test_latest_tag_must_be_exact_stable_same_repository_redirect(self):
        bad = [release.LATEST, release.ROOT + '/releases/tag/v1.8.1-rc1',
               'https://evil.example/lonewolf0622/HelixSR/releases/tag/v1.8.1',
               PAGE + '#digest', PAGE + '?download=1',
               'http://github.com/lonewolf0622/HelixSR/releases/tag/v1.8.1']
        for page in bad:
            with self.subTest(page=page), self.assertRaises(ValueError):
                self.fetch(page=page)

    def test_expanded_assets_and_head_final_hosts_are_bounded(self):
        for expanded in (EXPANDED + '?x=1', EXPANDED + '#x',
                         'https://evil.example/lonewolf0622/HelixSR/releases/expanded_assets/v1.8.1'):
            with self.subTest(expanded=expanded), self.assertRaises(ValueError):
                self.fetch(expanded=expanded)
        for target in ('https://evil.example/asset', ASSET + '#x',
                       ASSET + '?untrusted=1', 'http://release-assets.githubusercontent.com/asset'):
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.fetch(asset_final=target)

    def test_digest_must_be_in_unique_exact_asset_row(self):
        bad = [
            row(href=HREF.replace('v1.8.1', 'v1.8.0')),
            row(href=HREF.replace('HelixSR-1.8.1.zip', 'other.zip')),
            row(copies=0),
            row(copies=2),
            row(digest='x' * 64),
            row() + row(),
            row(href=HREF.replace('v1.8.1', 'v1.8.0')) + row(copies=0),
        ]
        for html in bad:
            with self.subTest(html=html[:100]), self.assertRaises(ValueError):
                self.fetch(html=html)

    def test_html_and_head_size_are_bounded_and_exact(self):
        with self.assertRaisesRegex(ValueError, 'too large'):
            self.fetch(html='x' * (release.MAX_HTML_BYTES + 1))
        for header in ({}, {'Content-Length': '54 MB'}, {'Content-Length': '56,650,779'},
                       {'Content-Length': '0'},
                       {'Content-Length': str(release.MAX_RELEASE_BYTES + 1)}):
            with self.subTest(header=header), self.assertRaises(ValueError):
                self.fetch(head=header)

    def test_same_version_replacement_rechecks_digest_and_exact_size(self):
        replacement = 'a' * 64
        first, _, _ = self.fetch()
        second, _, _ = self.fetch(html=row(digest=replacement),
                                  head={'Content-Length': '56650780'})
        self.assertEqual(first['version'], second['version'])
        self.assertNotEqual(first['sha256'], second['sha256'])
        self.assertEqual(second['size'], 56650780)

    def test_redirect_handler_rejects_foreign_targets_before_following(self):
        redirect = release._Redirect(release._tag_page)
        with self.assertRaisesRegex(ValueError, 'redirect'):
            redirect.redirect_request(None, None, 302, 'Found', {},
                                      'https://evil.example/release')

    def test_asset_head_stays_head_across_allowed_redirects_and_hop_cap(self):
        redirect = release._Redirect(lambda url: release._asset_target(url, ASSET))
        request = release.urllib.request.Request(ASSET, method='HEAD')
        for hop in range(3):
            with self.subTest(hop=hop):
                request = redirect.redirect_request(request, None, 302, 'Found', {}, CDN)
                self.assertEqual(request.get_method(), 'HEAD')
                self.assertEqual(request.full_url, CDN)
        with self.assertRaisesRegex(ValueError, 'redirect'):
            redirect.redirect_request(request, None, 302, 'Found', {}, CDN)

    def test_vendored_parser_decodes_html_entities_in_asset_link(self):
        parser = release._AssetRows(HREF)
        parser.feed(row(href=HREF.replace('.zip', '.z&#105;p')))
        parser.close()
        self.assertEqual(parser.digest(), DIGEST)

    def test_fresh_process_imports_without_standard_html_or_markupbase(self):
        modules = str(Path(__file__).resolve().parents[1] / 'py_modules')
        script = '''import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'html' or fullname.startswith('html.') or fullname == '_markupbase':
            raise ModuleNotFoundError(fullname)
sys.meta_path.insert(0, Block())
for name in list(sys.modules):
    if name == 'html' or name.startswith('html.') or name == '_markupbase':
        del sys.modules[name]
sys.path.insert(0, sys.argv[1])
import github_release
assert github_release._AssetRows
assert 'html.parser' not in sys.modules
assert '_markupbase' not in sys.modules
'''
        result = subprocess.run([sys.executable, '-S', '-c', script, modules],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
