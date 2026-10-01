# Device actions: other apps on the iPhone

This guide is for teams whose web app should start something in another app of
the iPhone from a button: a **route** in a navigation app, a **reminder**, a
**contact**, a **phone call**. The app does it with official iOS interfaces
(map links, Reminders, Contacts, `tel:`); your web app only says what.

**Calendar events are deliberately not included.** They go through Microsoft
(Outlook), the app neither creates events in the iPhone calendar nor reads it.

Package: [`@bmsuisse/app-native`](../packages/app-native), file
[`deviceActions.ts`](../packages/app-native/src/deviceActions.ts). There is
nothing to do in the backend.

```ts
import { navigate, addReminder, saveContact, callPhone } from '@bmsuisse/app-native'
```

## The four actions at a glance

| Function      | What it does                                      | Capability   | The user is asked                                              |
| ------------- | ------------------------------------------------- | ------------ | -------------------------------------------------------------- |
| `navigate`    | Starts a route in Apple Maps, Google Maps or Waze | –            | the first time: which navigation app                           |
| `addReminder` | Creates a reminder in Apple Reminders             | `deviceApps` | by default: a confirmation dialog                              |
| `saveContact` | Saves a contact in the address book               | `deviceApps` | by default: the system contact form, where they can still edit |
| `callPhone`   | Starts a phone call                               | –            | iOS asks before dialing                                        |

`navigate` and `callPhone` only open another app, like a link would, so they need
no capability. `addReminder` and `saveContact` write data on the device: the app
must have enabled **`deviceApps`** for your web app, otherwise they respond
`{ ok: false, error: 'capability' }`. `can('deviceApps')` tells you. (The app reads
the details first: a call with invalid details answers `invalid`, also without the
capability.)

## Response and errors

Every action responds with the same shape:

```ts
type DeviceActionResult = {
  ok: boolean
  message: string // a finished sentence for the user
  error?:
    | 'invalid'
    | 'unknownAction'
    | 'capability'
    | 'denied'
    | 'cancelled'
    | 'unavailable'
    | 'failed'
  [extra: string]: unknown // e.g. app: 'google', waypoints_ignored: 'true', list: 'Reminders'
}
```

| `error`         | Meaning                                                                                                                                                                                                   | What to do                                |
| --------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------- |
| `invalid`       | Details missing or unreadable (no title, no destination, a contact without a name, …)                                                                                                                     | Fix the call                              |
| `capability`    | `deviceApps` is not enabled for your web app                                                                                                                                                              | Ask the app team                          |
| `denied`        | The user has not allowed access to Reminders or Contacts                                                                                                                                                  | Show `message`, it says where to allow it |
| `cancelled`     | The user cancelled the question, the contact form or the choice of the navigation app. Also: a reminder with `confirm: true` while the app is not in the foreground, because the question cannot be shown | Accept it, do not ask again               |
| `unavailable`   | Not possible right now: the navigation app or the call could not be opened, there is no reminders list on the iPhone, the contact form cannot be shown, or you are not in the app                         | Show `message` or hide the button         |
| `unknownAction` | The app is too old to know the action                                                                                                                                                                     | Hide the button                           |
| `failed`        | Saving failed                                                                                                                                                                                             | Show `message`                            |

`message` comes from the app and is **German**. Where the app sends none (for
example `capability`) or the page runs outside the app, the package fills in a
short English sentence. So `message` is always a string, but do not rely on its
wording: show your own texts based on `error`, and use `message` as a fallback.

Further fields are extra information and always strings.

## Confirmation: `confirm`

`addReminder` and `saveContact` take `confirm` (default `true`):

- **`true`**: the user sees what happens first. A contact opens in the system
  contact form, where they can change everything before saving. A reminder comes
  as a question ("Create reminder … ?"). The app must be in the foreground.
- **`false`**: the app saves right away, without the question or the form. Use it
  only where the user has clearly asked for exactly this.

**Both modes need the iOS access** to Reminders or Contacts, which the user gives
once. Without it the answer is `denied`, also for a contact with `confirm: true`
(the form does not open then).

## iOS access

The first time, iOS asks for access to Reminders or Contacts. The user can
change it in the app's iOS settings and in the Info tab of the app, section
"Andere Apps". The app **only creates**: it has no function that reads reminders
or contacts, and your web app has no way to read them either.

If access was never given and the app cannot ask (not in the foreground), the answer
is `denied` with a `message` that says where to allow it.

## `navigate`

```ts
type Place = { address?: string; name?: string; latitude?: number; longitude?: number }

navigate({
  destination: Place | string, // text = address
  waypoints?: (Place | string)[],
  mode?: 'driving' | 'walking' | 'transit' | 'cycling', // default driving
  app?: 'apple' | 'google' | 'waze',
})
// or flat: navigate({ address }) / navigate({ latitude, longitude, name })
```

- A place needs an address or valid coordinates. With both, **coordinates win**. A
  `name` alone is only a label: the app answers `invalid`, and a stop with only a
  name is dropped.
- **Which app:** `app` if given and installed, otherwise the user's choice. The
  first time (with more than one navigation app installed) the app asks and
  remembers the answer; the user can change it in the Info tab.
- **Stops:** only Google Maps can take `waypoints`. If you give stops and no `app`,
  the app uses Google Maps if it is installed. With Apple Maps or Waze the stops are
  dropped and the response carries `waypoints_ignored: 'true'`; point it out to the
  user.
- **Travel mode:** Apple Maps has no cycling (it uses driving), Waze only drives.
- A route started from a web app **always opens on the iPhone** (only the BrAIn
  voice assistant opens it on the CarPlay display). If the app is not in the
  foreground (background, locked iPhone), the user gets a notification "Route nach
  … starten" to tap instead; the response is still `ok`.

## `addReminder`

```ts
addReminder({
  title: string,
  due?: string, // ISO 8601, see below
  allDay?: boolean, // treat `due` as all day although it has a time
  notes?: string,
  priority?: 'high' | 'medium' | 'low',
  list?: string, // name of the reminders list; otherwise the default list
  url?: string, // http(s)
  confirm?: boolean,
})
```

A timed `due` also sets an alarm at that moment. The response carries `list` (the
list the reminder went into).

The app is forgiving, and does not tell you: a `due` it cannot read is ignored (the
reminder is created **without** a due date, no `invalid`), a `url` that is not
`http(s)` is dropped, an unknown `priority` means none, and an unknown `list` name
falls back to the default list (names match without regard to case). Look at `list` in
the response to see where the reminder went.

## `saveContact`

```ts
saveContact({
  givenName?: string,
  familyName?: string,
  organization?: string, // at least one of these three
  jobTitle?: string,
  phones?: (string | { label?: 'mobile' | 'work' | 'home' | 'main' | 'other'; value: string })[],
  emails?: (string | { label?: 'work' | 'home' | 'other'; value: string })[],
  address?: { street?: string; postalCode?: string; city?: string; country?: string },
  url?: string, // http(s)
  confirm?: boolean,
})
```

A `url` that is not `http(s)` is dropped. Without a `label`, a phone number or email
counts as "work". The address is saved as a
work address, `url` as a work website. The type forces one of the three name fields;
at runtime the app answers `invalid` if all are missing.

## `callPhone`

```ts
callPhone({ number: string }) // preferably international: '+41 44 000 00 00'
```

The app keeps only digits and a leading `+` (iOS does not accept spaces in `tel:`).
iOS asks before it dials.

## Dates

`due` is ISO 8601:

| You send                      | The app understands                                     |
| ----------------------------- | ------------------------------------------------------- |
| `'2026-10-02'`                | all day                                                 |
| `'2026-10-02T09:00'`          | 09:00 in the time zone of the **iPhone**                |
| `'2026-10-02T09:00:00+02:00'` | exactly that moment (also `Z` and fractions of seconds) |

Two helpers write a JavaScript `Date` the right way:

```ts
import { toIsoWithOffset, toDateOnly } from '@bmsuisse/app-native'

toIsoWithOffset(new Date(2026, 9, 2, 9, 0)) // '2026-10-02T09:00:00+02:00' in Europe/Zurich
toDateOnly(new Date(2026, 9, 2, 0, 30)) // '2026-10-02' — the local date
```

Do not use `date.toISOString().slice(0, 10)` for an all-day reminder: that is the
**UTC** date and is one day off in the early morning (00:30 in Zurich is still
the day before in UTC).

## Outside the app

The same page also runs in a normal browser, so the functions fall back:

| Function                     | In a browser                                                                                               |
| ---------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `navigate`                   | opens `https://www.google.com/maps/dir/?api=1&destination=…` in a new tab (stops and travel mode included) |
| `callPhone`                  | opens a `tel:` link                                                                                        |
| `addReminder`, `saveContact` | `{ ok: false, error: 'unavailable' }`                                                                      |

## Examples

**"Go there" button in a list of jobs**

```ts
async function goThere(job: Job) {
  const res = await navigate({
    destination: { name: job.customer, address: `${job.street}, ${job.zip} ${job.city}` },
  })
  if (!res.ok && res.error !== 'cancelled') toast('Route could not be started', 'error')
}
```

**"Call back" as a reminder** (tomorrow at 9, with a question first)

```ts
const tomorrow9 = new Date()
tomorrow9.setDate(tomorrow9.getDate() + 1)
tomorrow9.setHours(9, 0, 0, 0)

const res = await addReminder({
  title: `Call ${contact.name} back`,
  notes: `Quote ${quote.number}`,
  due: toIsoWithOffset(tomorrow9),
  priority: 'high',
})
if (res.error === 'denied') toast(res.message, 'warning')
```

**Save a contact person** (the user checks the form, then saves)

```ts
await saveContact({
  givenName: person.firstName,
  familyName: person.lastName,
  organization: customer.name,
  phones: [{ label: 'mobile', value: person.mobile }],
  emails: [{ label: 'work', value: person.email }],
})
```

**Offer the buttons only where they work**

```ts
const canRemind = can('deviceApps') // false outside the app and without the capability
```
