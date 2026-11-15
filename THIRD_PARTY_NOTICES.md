# Third-party notices

Kintsugi's own code is licensed as described in [LICENSE.md](LICENSE.md). The repository also bundles the following
third-party code, which keeps its own licence.

## htmx 1.9.12

- **File:** `kintsugi/dashboard/static/htmx.min.js` (minified, unmodified)
- **Source:** https://github.com/bigskysoftware/htmx (release 1.9.12; licence text as published at
  https://unpkg.com/htmx.org@1.9.12/LICENSE)
- **Licence:** Zero-Clause BSD (0BSD). It requires no notice; this entry is here for provenance.

```
Zero-Clause BSD
=============

Permission to use, copy, modify, and/or distribute this software for
any purpose with or without fee is hereby granted.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL
WARRANTIES WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES
OF MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE
FOR ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY
DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN
AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT
OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
```

Python dependencies are installed separately, not bundled, and carry their own licences. As of 2026-11-15 none is
GPL-family. Most are permissive (MIT, BSD, Apache-2.0, PSF-2.0, ISC and similar). A few, such as certifi and tqdm, are
under the weak-copyleft MPL-2.0, which applies only to their own files. A CUDA build of PyTorch also pulls NVIDIA's
runtime libraries (the `nvidia-*` packages), which are under NVIDIA's proprietary licences; a CPU-only install does not
include them.
