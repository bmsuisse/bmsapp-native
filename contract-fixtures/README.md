# contract-fixtures

Shared sample payloads for both packages. The message format is written
**by hand** on both sides (TypeScript types in `packages/app-native/src`,
Pydantic models in `python/app-native`) — these files keep the two in sync:

- `python/app-native/tests/test_contract_fixtures.py` validates each file
  with the Pydantic models and checks that it serializes back unchanged.
- `packages/app-native/test/contract.test.ts` builds the same payloads as
  typed TS objects (the compiler checks them against the types) and
  compares them with these files.

| File                       | Contents                                                              |
| -------------------------- | --------------------------------------------------------------------- |
| `widgets.json`             | dashboard widgets of every kind, incl. the newer form field types     |
| `live-activity-state.json` | a Live Activity state                                                 |
| `native-form.json`         | a native form (`showForm`) with every field type, pages, `submit`     |
| `native-content.json`      | native content (`showContent`) with every block type, actions, `then` |

Whoever adds or renames a field adds it here as well — then the tests of
the side that has not caught up yet fail.
