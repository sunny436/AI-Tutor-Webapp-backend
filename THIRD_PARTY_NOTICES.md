# Third-party notices

PadhAI is proprietary software of Networkers Home ([LICENSE.md](LICENSE.md)). This file holds the notices for
third-party material that is part of this repository's own files.

Packages installed from the npm and PyPI registries are not stored here. They are listed with exact versions in
`frontend/bun.lock` and `backend/requirements.lock`, and each one ships its own licence.

## 1. The "v1" starter kit (Midday Labs AB): MIT License

The project's first upload (`1e744df`, 2026-08-08) was built on Midday Labs AB's open-source "v1" starter kit. It
came with the MIT notice below, which used to be this repository's `LICENSE.md`. The web app's workspace still
carries the starter's design:
- its Turborepo layout;
- the packages still named `@v1/app`, `@v1/ui` and `@v1/typescript`.

The MIT License requires the notice to be kept with the software:

```text
The MIT License (MIT)

Copyright (c) 2024 Midday Labs AB.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## 2. Noto Sans (The Noto Project Authors): SIL Open Font License 1.1

The web app's typeface is served from `frontend/apps/app/src/fonts/noto-sans/`:
- `noto-sans-latin-wght.woff2`: Noto Sans (Latin);
- `noto-sans-devanagari-wght.woff2`: Noto Sans Devanagari, used for Hindi.

Both are Noto fonts by The Noto Project Authors, under the SIL Open Font License, Version 1.1. The licence's full
text, with the copyright notice, is
[`frontend/apps/app/src/fonts/noto-sans/OFL.txt`](frontend/apps/app/src/fonts/noto-sans/OFL.txt), beside the fonts.
It must stay there.
