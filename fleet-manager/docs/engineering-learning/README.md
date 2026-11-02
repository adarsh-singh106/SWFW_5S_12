# Engineering Learning Handbook

*Study the Fleet Manager as a sequence of real engineering commits.*

This handbook explains the reasons behind the code, the boundaries of each commit, and the checks a reader can reproduce. A guide records what its named commit established. The current learning checkpoint records progress and understanding separately; neither a commit nor a guide proves that a student can explain or apply the material independently.

## Reading order

Start with the foundation and inventory chunks, then study configuration, authentication, and verified SSH connectivity. A guide names its source checkpoint or the working-tree files it inspected. If your working tree contains newer files, use a guide's named commit when one is available.

| Guide | Commit baseline | Focus |
| --- | --- | --- |
| [Chunk 00: Python Engineering Foundation](00-python-foundation.md) | `46e78ca7a3873c2e33c2cd5797c4dd4c35c048b5` | Python 3.12, environment isolation, package metadata, locking, build flow, and development tools. |
| [Chunk 01: Inventory Domain and SQLite Persistence](01-inventory-persistence.md) | `de4241cdff035be6f3818897d814af8b084b87d3` | Node values, validation, service boundaries, SQLite constraints, concurrency, and focused repository tests. |
| [Chunk 02: Configuration and Authentication](02-configuration-authentication.md) | Chunk 02 source checkpoint | Environment settings, fail-closed startup, bearer-token guard, and standalone unit tests. |
| [Chunk 03: Verified SSH Connectivity](03-ssh-connectivity.md) | Chunk 03 source checkpoint | Pinned host keys, private-key authentication, bounded child processes, and classified SSH outcomes. |

## Choose a study path

- **Deep-learning path:** read the guide in order, run its exercises in an isolated directory, answer the interview questions, and explain each result in your own words.
- **Quick-revision path:** use the guide's artifact map, tradeoffs, and quick-reference sheet to refresh concepts before an interview or review.

For the current next action and evidence limits, read the [learning checkpoint](../LEARNING-STATE.md). The checkpoint may describe work newer than a guide's commit; always keep those two timelines distinct.
