# CarPlay

Since iOS 26, CarPlay shows widgets and Live Activities of **every** app on
the CarPlay dashboard, even if it isn't a CarPlay app
([Apple CarPlay Developer Guide](https://developer.apple.com/download/files/CarPlay-Developer-Guide.pdf),
chapters "Widgets in CarPlay" and "Live Activities in CarPlay"). Your web
app needs **nothing new** for this; it uses the existing paths:

- **Widgets:** `create_widget_feed_router()` / `send_widget_update()`
  (see [dashboard-widgets-guide.md](dashboard-widgets-guide.md)). The user
  adds the "Webapp-Widget" to the CarPlay dashboard in the iOS Settings under
  _General › CarPlay › (car) › Widgets_. CarPlay uses the small size the
  widget already has.
- **Live Activities:** `send_live_activity_update()` & co. (see
  [live-activities-guide.md](live-activities-guide.md)). CarPlay shows the
  compact presentation: icon, title, countdown or status, and progress.

## What fits in the car

Good for the car: "Next appointment 14:30 Müller AG", "Route: 3 of 8 stops",
"Revenue today". Short, readable at a glance, no interaction needed.

Not for the car: notification contents (Apple prohibits them on the CarPlay
screen) and anything that requires reading or typing.
