// Minimal service worker: web push receive + click-to-open, plus a
// pass-through fetch handler. Kept as plain JS, as in the original app.
self.addEventListener("install", (e) => self.skipWaiting());
self.addEventListener("activate", (e) => self.clients.claim());

self.addEventListener("push", (event) => {
  let data = { title: "Day Planner", body: "" };
  try {
    data = event.data.json();
  } catch {
    /* ignore */
  }
  event.waitUntil(
    self.registration.showNotification(data.title || "Day Planner", {
      body: data.body || "",
      icon: "/static/icons/icon.svg",
      data: { url: data.url || "/" },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(clients.openWindow(url));
});
