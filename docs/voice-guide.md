# Voice: dictation and microphone

This guide is for web apps that take **spoken input** on the iPhone and iPad: a
chat with an assistant, a note on an offer, a search by voice. Two ways, both need
the capability **`microphone`**:

- **`dictate()`**: the app opens a native sheet that listens and shows a live
  transcript; the page gets the text. The simplest way, and the one that works with
  the device's speech recognition.
- **`getUserMedia({ audio: true })`**: the page records the audio itself (for example
  with `MediaRecorder`, to send it to a transcription service of its own).

Package: [`@bmsuisse/app-native`](../packages/app-native), file
[`voice.ts`](../packages/app-native/src/voice.ts). There is nothing to do in the
backend.

```ts
import { dictate, can, hasFeature } from '@bmsuisse/app-native'
```

## `dictate(options?)`

| Option              | Type     | Meaning                                                   |
| ------------------- | -------- | --------------------------------------------------------- |
| `locale`            | string   | BCP-47, e.g. `'de-CH'`. Default: the device language      |
| `maxSeconds`        | number   | 1 to 120, default 60. The sheet ends by itself after that |
| `contextualStrings` | string[] | Names and terms the recognizer should expect, at most 50  |

It opens a sheet with a live transcript and **Done** and **Cancel**. The result is
`{ ok: true, text, locale }`; `locale` is the one that was used.

```ts
const spoken = await dictate({ locale: 'de-CH', contextualStrings: ['Lieferschein', 'Palette'] })
if (spoken.ok) messageInput.value += spoken.text
else if (spoken.error === 'denied') showHint('Allow the microphone for the app in Settings.')
else if (spoken.error !== 'cancelled') hideMicrophoneButton()
```

| `error`       | Meaning                                                                                                        |
| ------------- | -------------------------------------------------------------------------------------------------------------- |
| `cancelled`   | The user pressed Cancel                                                                                        |
| `denied`      | The user did not allow the microphone (or speech recognition) for the app                                      |
| `unavailable` | No recognizer for the locale or on this device, an app without the feature `dictate`, or outside the app       |
| `capability`  | The web app does not have `microphone`                                                                         |
| `invalid`     | Options out of range. The package answers this itself and does not ask the app; `message` is for the developer |

The package checks `maxSeconds` (1 to 120), `contextualStrings` (strings, at most 50)
and `locale` (a non-empty string) before it asks the app. In development builds it
also logs a warning. Nothing throws.

**Always keep a way to type.** Dictation does not exist in the browser or in an older
app; `hasFeature('dictate')` and `can('microphone')` tell whether to show the button:

```ts
const canDictate = can('microphone') && hasFeature('dictate')
```

## Recording audio in the page

With `microphone` the app grants `getUserMedia({ audio: true })` to the web app's
**own origin** after the iOS permission prompt. Without the
capability the request is denied (`NotAllowedError`). The feature flag is
`mediaCapture`.

```ts
if (can('microphone') && hasFeature('mediaCapture')) {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
  const recorder = new MediaRecorder(stream)
  // …
}
```

A page in the browser asks the browser's own permission as always, so the same code
runs in both. The app only grants it to the web app's own origin.

## Which one?

|                      | `dictate()`                       | `getUserMedia` + your service |
| -------------------- | --------------------------------- | ----------------------------- |
| Result               | text                              | audio you process yourself    |
| UI                   | native sheet with live transcript | yours                         |
| Works in the browser | no                                | yes                           |

## App versions without the feature

| App                                 | `dictate`     | `getUserMedia({ audio: true })`                       |
| ----------------------------------- | ------------- | ----------------------------------------------------- |
| Browser                             | `unavailable` | browser permission                                    |
| App without `features`              | `unavailable` | do not rely on it: check `hasFeature('mediaCapture')` |
| App with `dictate` / `mediaCapture` | native sheet  | granted with `microphone`                             |
