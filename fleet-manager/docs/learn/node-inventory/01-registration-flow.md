# 01: Follow a registration request

Drafted by Codex, 2026-10-12. Technical basis: [references](references.md). All data and responses below are illustrative design examples, not observed application output. Implementation is not yet approved.

[Feature guide](README.md) · [Current checkpoint](../../LEARNING-STATE.md)

## 1. What problem are we solving?

Imagine operating several Linux machines. Before selecting a machine to investigate, you need a named list of the machines you intend to manage. That list is the **node inventory**.

Our first feature lets an operator enter a machine's details and retrieve them later. Later features will use those records to decide which endpoint to contact.

The example operator enters:

| Field | Example | Meaning |
| --- | --- | --- |
| Name | Lab PC 1 | A human-readable label |
| Address | 192.0.2.10 | Where we intend to contact the machine |
| SSH port | 22 | Which TCP port its SSH service is expected to use |

`192.0.2.10` is an address reserved for documentation. Do not try to contact it; substitute your actual authorized machine only when we reach connectivity work.

A **node** means a machine we intend to manage. A **network endpoint** here means the address and port used to reach a service. Different addresses can lead to the same machine, and a saved address can later point elsewhere. An endpoint is not a verified machine identity.

## 2. Who does what?

Three participants matter in this first feature:

| Participant | Responsibility |
| --- | --- |
| Browser / frontend | Display the form, send entered values, and display results |
| Fleet Manager backend | Receive requests, validate input, coordinate storage, and report outcomes |
| Database | Store structured records so the backend can retrieve them later |

The future managed Linux node is another participant, but registration itself does not contact it. The address typed into the form is data being sent to Fleet Manager.

The browser and backend may run on your Windows machine for this feature. They are still separate programs with different responsibilities. A database may be an embedded library and local file; it does not necessarily require another server process. The specific implementation remains a decision to approve.

## 3. What travels between the browser and backend?

HTTP defines request and response messages. A request names an operation and resource; a response carries an outcome. A **method** such as GET or POST expresses the requested operation, a **path** identifies the resource, and a **body** can carry data. See [MDN's HTTP overview](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/Overview).

Our proposed API uses these two operations:

| Request | Intended behavior in Fleet Manager |
| --- | --- |
| `POST /nodes` | Ask Fleet Manager to register the supplied endpoint |
| `GET /nodes` | Ask Fleet Manager for its saved inventory |

An **API** is the agreed interface programs use to interact. Here, the agreement includes paths, accepted fields, and responses. These path names are our proposal, not names supplied automatically by HTTP.

Illustrative JSON body for POST:

```json
{
  "name": "Lab PC 1",
  "address": "192.0.2.10",
  "ssh_port": 22
}
```

JSON is a text format for structured data. The quoted names identify fields; their values follow the colons. `22` is a number, while `"22"` would be text. This example is data, not a command or a runnable Python program.

Notice that the request goes to **Fleet Manager's HTTP address**, not to `192.0.2.10:22`. The body describes a future SSH destination. Confusing these two destinations makes the data flow difficult to reason about.

## 4. Follow one successful registration

1. You fill in the form and press Add node.
2. Browser code sends the values to Fleet Manager using `POST /nodes`.
3. The backend checks whether the values satisfy the agreed rules. This is **validation**. Browser checks can help users, but the backend must also check because requests can come from other programs.
4. If valid, the backend asks the database to store a record. A record is one saved entry with named fields.
5. The database completes the save. We will study **commit**, the step that finalizes a database transaction, in the persistence lesson. Our application must wait for a successful commit before reporting a successful registration.
6. The backend sends a success response. The page shows the saved node and the observation label **Not checked**.
7. When the page later requests `GET /nodes`, the backend retrieves saved records and returns them for display.

This flow is our proposed application behavior. MDN's [client-server overview](https://developer.mozilla.org/en-US/docs/Learn_web_development/Extensions/Server-side/First_steps/Client-Server_overview) provides background on requests, backend processing, and responses.

**Persistence** means keeping data beyond the lifetime of the running program. A list held only in Python memory disappears when that process exits. Our target is a saved inventory that can be read after the application restarts. A restart experiment will test that specific behavior; it will not prove resilience to every disk or power failure.

## 5. What does success prove?

If registration succeeds, we have evidence that Fleet Manager accepted and saved the record. We have not tried SSH, verified the server's identity, inspected Linux, or collected a metric.

Saving a contact in a phone is similar: the saved contact can remain even while the person's phone is off. That is why the initial observation label is Not checked.

Later, an SSH probe will add an observation about a particular attempt. We will keep that separate from the existence of the inventory entry.

## 6. Follow the failures too

| Situation | Expected behavior to design and later verify |
| --- | --- |
| An input violates the agreed validation rules | Explain the invalid field; do not save a record |
| The same normalized address/port is already registered | Report a duplicate under the proposed endpoint rule; do not add another record |
| The backend knows the save failed before commit | Report failure; do not claim registration succeeded |
| The request commits, but the response never reaches the browser | The browser cannot yet know whether saving succeeded; refresh/query the inventory to investigate |

The final case is important: a missing response does not always mean the database write failed. We do not need to build a full retry system now, but should avoid promising certainty that the browser lacks.

Duplicate handling also has limits: two different addresses might reach the same machine. Our initial endpoint rule cannot establish physical-machine uniqueness. Exact normalization and identity rules need an implementation discussion.

## 7. Your first exercise

Without writing code yet, answer this scenario in your own words:

> You enter Lab PC 1's details, but that Linux machine is switched off. Fleet Manager and its database are running normally. Should saving the inventory entry still be possible? Which participant would need to contact the machine to find out whether SSH works?

Use two or three sentences. Point to section 2 or 4 if you need help; this checks the actual data flow rather than vocabulary recall.

<details>
<summary>Worked explanation to compare with your answer</summary>

Saving should still be possible if the input satisfies the rules and storage succeeds. Registration exchanges messages with Fleet Manager and its database. A later backend SSH check would contact the managed endpoint. That check has not happened, so the inventory entry remains Not checked.

</details>

## 8. Exact next action

Share your explanation from section 7, or the specific step that is unclear. We will then agree the input rules and propose your first focused coding task: a Python function that validates an SSH port. Before writing it, we will specify accepted types, allowed range, return behavior, and invalid-input behavior, then inspect concrete examples together.

That task will become part of the registration path after the feature design and implementation scope are approved. Runtime setup, dependencies, framework choice, and storage choice will be explained and authorized at the relevant boundary. There are no installation commands to run in this lesson.
