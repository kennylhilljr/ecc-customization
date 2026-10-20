# EARS Pattern Reference

Comprehensive documentation of EARS (Easy Approach to Requirements Syntax) patterns.

## Pattern Deep Dive

### Ubiquitous Pattern

**Syntax:** `THE [System] SHALL [behavior]`

**When to use:**
- System-wide constraints
- Security requirements
- Data integrity rules
- Performance requirements

**Examples:**
```
THE System SHALL encrypt all data at rest using AES-256
THE System SHALL log all authentication attempts
THE System SHALL respond to API requests within 200ms
THE System SHALL maintain an uptime of 99.9%
THE System SHALL support concurrent access by 1000 users
```

**Avoid:**
- Overusing for conditional behaviors (use WHEN/IF instead)
- Vague behaviors like "THE System SHALL be fast"

---

### Event-Driven Pattern

**Syntax:** `WHEN [event] THE [System] SHALL [response]`

**When to use:**
- User interactions (clicks, submits, navigates)
- API calls
- Timer events
- External triggers

**Examples:**
```
WHEN the user clicks the submit button THE System SHALL validate the form
WHEN a new order is placed THE System SHALL send a confirmation email
WHEN the session expires THE System SHALL redirect to the login page
WHEN the API receives a GET request THE System SHALL return the resource
WHEN the user uploads a file THE System SHALL scan it for malware
```

**Avoid:**
- Missing the trigger event
- Combining multiple events (use separate requirements)

---

### State-Driven Pattern

**Syntax:** `WHILE [state] THE [System] SHALL [behavior]`

**When to use:**
- Ongoing behaviors during a condition
- Mode-specific functionality
- Continuous monitoring

**Examples:**
```
WHILE the user is logged in THE System SHALL display the navigation bar
WHILE in maintenance mode THE System SHALL reject all write operations
WHILE processing a payment THE System SHALL display a loading indicator
WHILE offline THE System SHALL queue all pending changes
WHILE the battery is low THE System SHALL reduce background sync frequency
```

**Avoid:**
- Using for one-time events (use WHEN instead)

---

### Optional Feature Pattern

**Syntax:** `WHERE [feature is present] THE [System] SHALL [behavior]`

**When to use:**
- Feature flags
- Configuration-dependent behavior
- Plan/tier-specific features
- Regional features

**Examples:**
```
WHERE two-factor authentication is enabled THE System SHALL require a verification code
WHERE dark mode is selected THE System SHALL apply the dark theme
WHERE the premium plan is active THE System SHALL allow unlimited exports
WHERE GDPR compliance is required THE System SHALL display cookie consent
WHERE the debug flag is set THE System SHALL log detailed request information
```

**Avoid:**
- Using for conditional logic (use IF/THEN instead)

---

### Error Handling Pattern

**Syntax:** `IF [condition] THEN THE [System] SHALL [response]`

**When to use:**
- Error conditions
- Validation failures
- Edge cases
- Boundary conditions
- Exception handling

**Examples:**
```
IF the email format is invalid THEN THE System SHALL display "Invalid email address"
IF the password is less than 8 characters THEN THE System SHALL reject the input
IF the API returns a 500 error THEN THE System SHALL retry the request 3 times
IF the file size exceeds 10MB THEN THE System SHALL display "File too large"
IF the user has no items in cart THEN THE System SHALL disable the checkout button
IF the database connection fails THEN THE System SHALL serve cached data
```

**Key point:** Always specify the exact response, not just "handle the error"

---

### Complex Pattern

**Syntax:** `WHILE [state] WHEN [event] THE [System] SHALL [response]`

**When to use:**
- State + event combinations
- Context-sensitive actions
- Mode-specific triggers

**Examples:**
```
WHILE the cart is not empty WHEN the user clicks checkout THE System SHALL navigate to payment
WHILE in edit mode WHEN the user presses Escape THE System SHALL cancel changes
WHILE authenticated WHEN the session timeout warning appears THE System SHALL allow extension
WHILE offline WHEN the user submits a form THE System SHALL queue the submission
WHILE in admin mode WHEN a user is selected THE System SHALL show delete option
```

**Avoid:**
- Unnecessary complexity (use simpler patterns when possible)

---

## Combining Patterns

A requirement typically has 3-6 acceptance criteria using multiple patterns:

```markdown
### Requirement: User Login

#### Acceptance Criteria

1. WHEN the user submits valid credentials THE System SHALL create a session
2. WHEN the user submits valid credentials THE System SHALL redirect to the dashboard
3. IF the email is not registered THEN THE System SHALL display "Account not found"
4. IF the password is incorrect THEN THE System SHALL display "Invalid password"
5. IF the user fails login 5 times THEN THE System SHALL lock the account for 30 minutes
6. WHILE the account is locked THE System SHALL reject all login attempts
```

---

## Regex Patterns for Validation

For automated validation:

```javascript
const patterns = {
  ubiquitous:     /^THE\s+\S.+\s+SHALL\s+\S.+$/,
  eventDriven:    /^WHEN\s+\S.+\s+THE\s+\S.+\s+SHALL\s+\S.+$/,
  stateDriven:    /^WHILE\s+\S.+\s+THE\s+\S.+\s+SHALL\s+\S.+$/,
  optionalFeature:/^WHERE\s+\S.+\s+THE\s+\S.+\s+SHALL\s+\S.+$/,
  errorHandling:  /^IF\s+\S.+\s+THEN\s+THE\s+\S.+\s+SHALL\s+\S.+$/,
  complex:        /^WHILE\s+\S.+\s+WHEN\s+\S.+\s+THE\s+\S.+\s+SHALL\s+\S.+$/
};
```

---

## Anti-Patterns

### 1. Missing Keywords
```
Bad:  "When user clicks, show confirmation"
Good: "WHEN the user clicks the button THE System SHALL display confirmation"
```

### 2. Wrong Modal Verb
```
Bad:  "THE System MUST validate input"
Good: "THE System SHALL validate input"
```

### 3. Lowercase Keywords
```
Bad:  "When the user logs in the System shall..."
Good: "WHEN the user logs in THE System SHALL..."
```

### 4. Vague Behavior
```
Bad:  "THE System SHALL handle errors appropriately"
Good: "IF an error occurs THEN THE System SHALL display the error message and log details"
```

### 5. Multiple Behaviors
```
Bad:  "WHEN user clicks THE System SHALL validate, save, and redirect"
Good: Three separate requirements for validate, save, and redirect
```
