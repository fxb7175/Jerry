# Importable Anki package

The pull request system does not support binary `.apkg` diffs, so the importable package is stored as Base64 text.

## Recreate the `.apkg`

From the repository root, run:

```bash
base64 -d dist/japanese-vocab-eink.apkg.b64 > 日语词汇-eink.apkg
```

Then import `日语词汇-eink.apkg` into Anki.

## What this contains

`日语词汇-eink.apkg` is the original Japanese vocabulary deck rewritten with the e-ink black-and-white template from `tools/rewrite_anki_eink_template.py`.
