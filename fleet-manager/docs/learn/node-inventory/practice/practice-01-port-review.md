# Practice 01: Code Review — SSH Port Validator

**Series:** Fleet Manager Hands-on Practice\
**Topic:** Feature 1 — Node Inventory\
**Parent Lesson:** [⬅️ Document 04: Input Validation Contract](../04-input-validation-contract.md)\
**Associated Code:** [`validate_port.py`](validate_port.py)\

---

AI-drafted in the previous session; reviewed by Codex on 2026-10-13. The initial code and conversion example below are historical learning material. Current behavior is recorded in section 6. Technical basis: [Python references](../references.md).

## 1. Practice Code vs. Production Code

Student ne jo initial implementation likhi in [`validate_port.py`](validate_port.py):

```python
def validate_ssh_port(value: int) -> int | ValueError:
    if type(value) not in ['int', 'str']:
        raise ValueError("Invalid Port DataType")
    if value is str:
        for ch in value:
            if '0' < ch < '9':
                continue
            else:
                raise ValueError("Non-ASCII digits")

    if 1 <= int(value) <= 65535:
        return value
    else:
        raise ValueError("Invalid Port")

validate_ssh_port(22)
```

### Review Verdict:
**Status:** **Practice-level Code**.\
**Good Points:**
- Input type check karne ki koshish ki.
- Character-by-character digit check socha.
- TCP port boundary (1 to 65535) verify ki.

The original version failed at its first type guard for `22`. The current file fixes that failure; the remaining policy gaps are listed in section 6.

---

## 2. The 5 Issues & Fixes

### Issue 1: Type Object vs. String Name
* **Code:** `if type(value) not in ['int', 'str']:`
* **What Python does:** `type(22)` return karta hai `<class 'int'>` (ek type object), na ki string `'int'`.
* **Fix:** `if not isinstance(value, (int, str)):`

---

### Issue 2: Identity Check (`is`) vs Instance Check (`isinstance`)
* **Code:** `if value is str:`
* **What Python does:** `value` variable ek string instance hai (jaise `"22"`), wo `str` class object nahi hai. Yeh condition hamesha `False` aayegi.
* **Fix:** `if isinstance(value, str):`

---

### Issue 3: Boundary Inequality (`<` vs `<=`)
* **Code:** `if '0' < ch < '9':`
* **What Python does:** `<` strictly compare karta hai. Agar character `'0'` ya `'9'` aa gaya (jaise port `"20"` ya `"90"`), toh yeh fail ho jayega kyunki `'0' < '0'` False hota hai.
* **Fix:** `'0' <= ch <= '9'` for ASCII digits. `ch.isdigit()` accepts additional Unicode characters and is not equivalent to this policy; also reject an empty string.

---

### Issue 4: Return Value Sanitization
* **Code:** `return value`
* **What Python does:** Agar input string `"22"` tha, toh string hi return hoga. API contract ke hisaab se integer port expect kiya jata hai.
* **Fix:** `return int(value)`.

---

### Issue 5: Boolean Edge Case
* Python mein `bool` actually `int` ka subclass hota hai (`isinstance(True, int) == True`).
* **Fix:** Explicit guard: `if isinstance(value, bool): raise ValueError(...)`.

---

## 3. Conversion Pattern (EAFP): illustrative, incomplete validation

EAFP means attempting an operation and handling its exception. It is a control-flow style, not a production-readiness guarantee. This earlier example accepts floats such as `22.5` by truncating them, and accepts text forms excluded by Document 04. The current student file rejects floats, but still needs input-policy alignment. Do not copy this example as the completed validator:

```python
def validate_ssh_port(value: int | str) -> int:
    """
    Validates and normalizes an SSH port number.
    Returns: int between 1 and 65535.
    Raises: ValueError if invalid.
    """
    if isinstance(value, bool):
        raise ValueError("Port cannot be a boolean value")

    try:
        port = int(value)
    except (ValueError, TypeError):
        raise ValueError(f"Port must be a valid integer, got: {value!r}")

    if not (1 <= port <= 65535):
        raise ValueError(f"Port must be between 1 and 65535, got: {port}")

    return port
```

---

## 4. Student Doubt: What does `{value!r}` mean?

> **Question:** *"Ye kya likha hai bhai `{value!r}`?"*

### The Explanation:
Python ke f-string mein `{value!r}` ka matlab hota hai: **`repr(value)`** ko call karna.

* **Normal `{value}`** uses the formatting protocol with an empty format specification; for the built-in examples below, its output matches `str(value)`.
* **`{value!r}`** $\to$ calls **`repr(value)`** (Developer/debugger representation with type hints like quotes).

### Comparison in Error Messages & Logs:

| Input `value` | Normal `{value}` | `{value!r}` (X-ray view!) | What `!r` reveals in these examples |
| :--- | :--- | :--- | :--- |
| String `"22"` | `got: 22` | `got: '22'` | Quotes `'22'` saaf batate hain ki string aayi hai, int nahi. |
| Integer `22` | `got: 22` | `got: 22` | Bina quotes ke number dikhta hai. |
| Empty string `""` | `got: ` | `got: ''` | Normal wale mein blank lagega; `!r` mein quotes dikhenge. |
| Space string `" "` | `got:  ` | `got: ' '` | Pakad mein aayega ki user ne whitespace daala hai. |
| `None` | `got: None` | `got: None` | Dono mein `None` dikhega. |

> **Takeaway:**\
> `{value}` hota hai user ke liye display.\
> `{value!r}` hota hai developer ke liye debugging X-ray, taaki error logs mein type aur invisible characters (spaces) turant pakad mein aa sakein.

---

## 5. Student Doubt: `isinstance()` kyon use karte hain? Kya kahani hai iske peeche?

> **Question:** *"Apan `isinstance()` kyon use kar rahe hain? Kya kahani hai iske peeche?"*

### The Story: `type()` vs `isinstance()`

#### 1. Aadhar Card (`type`) vs DNA Test (`isinstance`)
* `type(x) == int` check karta hai: *"Kya tu bilkul strictly `int` hi hai?"* (Exact match).
* `isinstance(x, int)` check karta hai: *"Kya tu `int` ya uske parivaar (subclass/inheritance) ka hissa hai?"* (Family/DNA test).

#### 2. The Great Boolean History in Python
Python ke shuruati dino mein (Python 2.3 se pehle) `bool` datatype tha hi nahi! Log `0` aur `1` use karte the true/false ke liye.
Jab Python ne baad mein `bool` add kiya, toh puraana code crash na ho isliye unhone `bool` ko `int` ka beta bana diya:
```python
class bool(int):
    ...
```
Iska natija:
```python
isinstance(True, int)   # True! (Kyunki bool int ka child hai)
type(True) == int       # False! (Kyunki exact type bool hai)
```
Jab hume `bool` ko rokhna hota hai, hum likhte hain:
```python
if isinstance(value, bool):
    raise ValueError("Port cannot be a boolean")
```
Yeh `True` aur `False` dono ko pakad leta hai!

#### 3. Flexibility & Clean Syntax
`isinstance` multiple types ko tuple mein ek sath check kar sakta hai:
```python
isinstance(value, (int, str))  # Clean & Pythonic
# vs
type(value) in (int, str)      # Exact types only; excludes subclasses
```

---

## 6. Current verification and next step

Codex ran 15 core cases on 2026-10-13: five accepted inputs (`22`, `"22"`, `1`, `65535`, `"0022"`) returned integers; ten invalid inputs (`True`, `False`, `22.0`, `22.5`, `None`, `0`, `-5`, `70000`, `"abc"`, `""`) raised `ValueError`. These were session checks, not a saved automated test suite.

Five additional inputs were accepted although the proposed strict policy would reject them: `" 22 "`, `"+22"`, `"2_2"`, Arabic-Indic decimal digits, and `b"22"`. The annotation does not enforce types at runtime. The float rejection message also incorrectly says boolean, and the docstring omits accepted strings.

Next: agree the input policy and align the student implementation with it. This commit preserves the practice attempt, not a production-ready validator. After that, learn persistence through one save/read exercise.

Student apne code [`validate_port.py`](validate_port.py) ko update karega aur edge cases test karega.\
Jab yeh complete ho jaye, tab wapas parent lesson par proceed karenge:\
👉 [Back to Document 04: Input Validation Contract](../04-input-validation-contract.md)
