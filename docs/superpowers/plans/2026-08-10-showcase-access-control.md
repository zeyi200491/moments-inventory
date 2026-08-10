# Showcase Access Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add lightweight access control to the static CCD showcase site so customers enter a weekly password before viewing inventory.

**Architecture:** Keep the site static. During `showcase-build`, optionally encrypt the generated products payload into `products.encrypted.json`; the browser unlocks it with the customer password using WebCrypto. The visible page adds Xingxing CCD ownership language and an authorized partner notice.

**Tech Stack:** Python, pytest, `cryptography` AES-GCM, browser WebCrypto, static HTML/CSS/JavaScript, Windows `.bat`.

---

### Task 1: Encrypted Products Payload

**Files:**
- Modify: `src/moments_inventory/showcase.py`
- Test: `tests/test_showcase.py`

- [x] **Step 1: Write the failing test**

```python
def test_build_showcase_site_can_encrypt_products_with_access_password(tmp_path: Path) -> None:
    result = build_showcase_site(..., access_password="week-pass")
    assert not (result.output_dir / "products.json").exists()
    encrypted = json.loads((result.output_dir / "products.encrypted.json").read_text(encoding="utf-8"))
    decoded = json.loads(decrypt_showcase_payload(encrypted, "week-pass").decode("utf-8"))
    assert decoded["products"][0]["source"] == "星星ccd货源"
```

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_showcase.py::test_build_showcase_site_can_encrypt_products_with_access_password -q`

Expected: FAIL because `decrypt_showcase_payload` and `access_password` do not exist.

- [x] **Step 3: Implement minimal encryption**

Use PBKDF2-HMAC-SHA256 to derive a 256-bit key from the weekly password and encrypt the product JSON with AES-GCM. When a password is provided, write `products.encrypted.json` and remove any stale `products.json`.

- [x] **Step 4: Verify test passes**

Run: `python -m pytest tests/test_showcase.py::test_build_showcase_site_can_encrypt_products_with_access_password -q`

Expected: PASS.

### Task 2: Access Gate UI

**Files:**
- Modify: `src/moments_inventory/showcase.py`
- Test: `tests/test_showcase.py`

- [x] **Step 1: Write expectations in the encrypted build test**

```python
assert "本周口令" in html
assert "本库存展示页归星星CCD所有" in html
assert "当前授权合作方：星星CCD直营" in html
assert "products.encrypted.json" in js
```

- [x] **Step 2: Implement static page changes**

Add an access gate, ownership notice, authorized partner area, encrypted data loading, password remember-for-7-days behavior, and wrong-password messaging.

- [x] **Step 3: Verify test passes**

Run: `python -m pytest tests/test_showcase.py::test_build_showcase_site_can_encrypt_products_with_access_password -q`

Expected: PASS.

### Task 3: CLI And Publishing Script

**Files:**
- Modify: `src/moments_inventory/cli.py`
- Modify: `publish_showcase_site.bat`
- Test: `tests/test_cli_batch_run.py`

- [x] **Step 1: Write the failing parser assertion**

```python
build_args = parser.parse_args(["showcase-build", "--access-password", "week-pass"])
assert build_args.access_password == "week-pass"
```

- [x] **Step 2: Implement CLI plumbing**

Add `--access-password` to `showcase-build` and pass it into `build_showcase_site`.

- [x] **Step 3: Update publish script**

Prompt for `SHOWCASE_PASSWORD`; fail fast when empty; pass it to `showcase-build --access-password`.

- [x] **Step 4: Verify tests**

Run: `python -m pytest tests/test_showcase.py tests/test_cli_batch_run.py::test_cli_accepts_showcase_commands -q`

Expected: PASS.
