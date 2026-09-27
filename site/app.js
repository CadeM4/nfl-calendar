/* Static subscription UI. All schedule claims come from published JSON. */
(() => {
  "use strict";
  const $ = (selector) => document.querySelector(selector);
  const state = { teams: [], conference: "all", query: "", masterURL: null };
  const zone = "America/New_York";
  const baseURL = new URL("./", window.location.href);
  const dateFormat = new Intl.DateTimeFormat("en-US", { timeZone: zone, month: "short", day: "numeric", weekday: "short" });
  const timeFormat = new Intl.DateTimeFormat("en-US", { timeZone: zone, hour: "numeric", minute: "2-digit", timeZoneName: "short" });
  const stampFormat = new Intl.DateTimeFormat("en-US", { timeZone: zone, month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short" });
  const dayFormat = new Intl.DateTimeFormat("en-CA", { timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit" });
  let toastTimer;

  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function validDate(value) {
    if (typeof value !== "string" || !value) return null;
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  function safeURL(value) {
    try {
      const url = new URL(value);
      return ["https:", "http:"].includes(url.protocol) ? url : null;
    } catch (_) { return null; }
  }

  function feedURL(filename) {
    const url = new URL(filename, baseURL);
    // Production Pages uses HTTPS; localhost remains usable during preview.
    if (url.hostname !== "localhost" && url.hostname !== "127.0.0.1") url.protocol = "https:";
    return url.href;
  }

  function activateSubscription(element, filename, accessibleName) {
    element.href = feedURL(filename).replace(/^https?:/, "webcal:");
    element.removeAttribute("aria-disabled");
    if (accessibleName) element.setAttribute("aria-label", accessibleName);
  }

  function notify(text) {
    clearTimeout(toastTimer);
    $("#toast").textContent = text;
    $("#toast").classList.add("visible");
    toastTimer = setTimeout(() => $("#toast").classList.remove("visible"), 4200);
  }

  function showMessage(text) {
    $("#data-message").textContent = text;
    $("#data-message").hidden = false;
  }

  async function fetchJSON(filename) {
    const response = await fetch(new URL(filename, baseURL), { cache: "no-store" });
    if (!response.ok) throw new Error(`${filename}: HTTP ${response.status}`);
    return response.json();
  }

  function validateStatus(data) {
    if (!data || !Number.isInteger(data.season) || data.season < 2000 || !Array.isArray(data.teams) || !data.counts || !validDate(data.fetched_at)) throw new Error("Publication status is unavailable or invalid.");
    if (!["regular", "postseason", "teams"].every(key => Number.isInteger(data.counts[key]) && data.counts[key] >= 0)) throw new Error("Publication counts are invalid.");
    if (data.counts.regular === 0 || data.teams.length === 0) throw new Error("No published regular season is available.");
    return data;
  }

  function renderStatus(data) {
    const season = data.season;
    document.title = `NFL Calendar ${season}–${String(season + 1).slice(-2)} · Every game. One calendar.`;
    document.querySelectorAll("[data-season-label]").forEach(el => { el.textContent = `${season} — ${season + 1}`; });
    document.querySelectorAll("[data-short-season]").forEach(el => { el.textContent = `${String(season).slice(-2)} / ${String(season + 1).slice(-2)}`; });
    $("#regular-count").textContent = data.counts.regular;
    $("#team-count").textContent = data.counts.teams;
    $("#postseason-count").textContent = data.counts.postseason;
    const fetched = validDate(data.fetched_at);
    const hours = (Date.now() - fetched.getTime()) / 3600000;
    const stale = hours > 18;
    $("#freshness").classList.add(stale ? "stale" : "good");
    $("#freshness-title").textContent = stale ? "Published feed may be out of date" : "Published schedule available";
    $("#last-published").textContent = `Retrieved ${stampFormat.format(fetched)}`;
    if (stale) showMessage("The published schedule is more than 18 hours old. The last valid feed is still available; check your update workflow if this timestamp does not advance.");
    if (data.tbd && [data.tbd.time, data.tbd.date, data.tbd.broadcast].every(value => Number.isInteger(value) && value >= 0)) {
      $("#tbd-note").textContent = `Still TBD: ${data.tbd.date} dates · ${data.tbd.time} kickoff times · ${data.tbd.broadcast} broadcasts.`;
    }
    const source = safeURL(data.source?.url);
    if (source) {
      $("#source-link").href = source.href;
      $("#source-link").textContent = `${data.source.name || "Schedule source"} ↗`;
    } else {
      $("#source-link").removeAttribute("href");
      $("#source-link").textContent = "Source details unavailable";
    }
    state.masterURL = feedURL(`nfl-${season}.ics`);
    $("#feed-url").value = state.masterURL;
    activateSubscription($("#master-subscribe"), `nfl-${season}.ics`);
    activateSubscription($("#primetime-subscribe"), "primetime.ics");
    $("#master-copy").disabled = false;
    state.teams = data.teams.filter(team => team && typeof team.name === "string" && typeof team.id === "string" && /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(team.slug) && Number.isInteger(team.count)).sort((a, b) => a.name.localeCompare(b.name));
    renderTeams();
  }

  function renderTeams() {
    const grid = $("#team-grid");
    grid.replaceChildren();
    const teams = state.teams.filter(team => (state.conference === "all" || team.conference === state.conference) && `${team.name} ${team.id} ${team.division || ""}`.toLowerCase().includes(state.query));
    $("#team-results").textContent = `${teams.length} team calendars shown.`;
    if (!teams.length) {
      grid.append(node("p", "empty-state", state.teams.length ? "No teams match. Try another name or conference." : "Team feeds will appear when the published schedule is available."));
      return;
    }
    teams.forEach(team => {
      const card = node("a", "team-card");
      activateSubscription(card, `${team.slug}.ics`, `Subscribe to ${team.name}: ${team.count} games`);
      const monogram = node("span", "team-monogram", team.id);
      monogram.setAttribute("aria-hidden", "true");
      const content = node("span", "team-card-content");
      content.append(node("strong", "", team.name), node("small", "", `${team.conference || "NFL"} · ${team.count} games`));
      const arrow = node("span", "arrow", "↗");
      arrow.setAttribute("aria-hidden", "true");
      card.append(monogram, content, arrow);
      grid.append(card);
    });
  }

  function roundName(game) {
    if (game.season_type === "POST") return ({ 1: "Wild Card", 2: "Divisional", 3: "Conference", 5: "Super Bowl" })[game.week] || "Postseason";
    return `Week ${game.week}`;
  }

  function teamName(id) {
    if (!id) return "Team TBD";
    return state.teams.find(team => team.id === id)?.name || id;
  }

  function renderFixtures(schedule) {
    if (!schedule || !Array.isArray(schedule.games)) throw new Error("Schedule preview is unavailable.");
    const now = Date.now();
    const dateParts = Object.fromEntries(dayFormat.formatToParts(new Date()).filter(part => part.type !== "literal").map(part => [part.type, part.value]));
    const today = `${dateParts.year}-${dateParts.month}-${dateParts.day}`;
    const games = schedule.games.filter(game => {
      if (!["REG", "POST"].includes(game.season_type) || game.status === "cancelled" || game.status === "canceled") return false;
      const time = !game.time_tbd && !game.date_tbd ? validDate(game.start_time) : null;
      return time ? time.getTime() >= now : typeof (game.date || game.week_date) === "string" && (game.date || game.week_date) >= today;
    }).sort((a, b) => (a.start_time || a.date || a.week_date || "9999").localeCompare(b.start_time || b.date || b.week_date || "9999")).slice(0, 5);
    const fixtures = $("#fixtures");
    fixtures.replaceChildren();
    if (!games.length) {
      fixtures.append(node("p", "empty-state", "No upcoming games are currently published. Newly announced postseason games will appear after a successful schedule refresh."));
      return;
    }
    games.forEach(game => {
      const row = node("article", "fixture");
      const kickoff = !game.time_tbd && !game.date_tbd ? validDate(game.start_time) : null;
      const date = !game.date_tbd && game.date ? validDate(`${game.date}T12:00:00Z`) : kickoff;
      const dateCell = node("div", "fixture-date" + (!date ? " unconfirmed" : ""), date ? dateFormat.format(date) : "Date TBD");
      dateCell.append(node("span", "fixture-week", roundName(game)));
      const match = node("div", "fixture-match");
      const title = node("strong");
      title.append(node("span", "", teamName(game.away)), node("span", "at", " @ "), node("span", "", teamName(game.home)));
      match.append(title);
      const venue = [game.venue?.name, game.venue?.city].filter(Boolean).join(" · ");
      if (venue) match.append(node("span", "fixture-venue", venue));
      const timeCell = node("div", "fixture-time" + (!kickoff ? " unconfirmed" : ""), kickoff ? timeFormat.format(kickoff) : "Time TBD");
      const network = node("div", "fixture-network");
      const broadcast = game.broadcast || {};
      const tv = Array.isArray(broadcast.tv) ? broadcast.tv.filter(value => typeof value === "string" && value) : [];
      const streaming = Array.isArray(broadcast.streaming) ? broadcast.streaming.filter(value => typeof value === "string" && value) : [];
      if (tv.length) network.append(node("span", "", `TV: ${tv.join(", ")}`));
      if (streaming.length) network.append(node("span", "", `Stream: ${streaming.join(", ")}`));
      if (!tv.length && !streaming.length) network.append(node("span", "unconfirmed", "Broadcast TBD"));
      row.append(dateCell, match, timeCell, network);
      fixtures.append(row);
    });
  }

  $("#master-copy").addEventListener("click", async () => {
    if (!state.masterURL) return;
    try {
      await navigator.clipboard.writeText(state.masterURL);
      notify("Subscription URL copied. Paste it into your calendar app.");
    } catch (_) {
      const input = $("#feed-url");
      input.closest("details").open = true;
      input.focus();
      input.select();
      notify("Select and copy the highlighted subscription URL.");
    }
  });
  $("#team-search").addEventListener("input", event => { state.query = event.target.value.trim().toLowerCase(); renderTeams(); });
  document.querySelectorAll("[data-conference]").forEach(button => button.addEventListener("click", () => {
    state.conference = button.dataset.conference;
    document.querySelectorAll("[data-conference]").forEach(item => {
      const active = item === button;
      item.classList.toggle("active", active);
      item.setAttribute("aria-pressed", String(active));
    });
    renderTeams();
  }));

  async function initialize() {
    const [statusResult, scheduleResult] = await Promise.allSettled([fetchJSON("status.json"), fetchJSON("schedule.json")]);
    let status;
    try {
      if (statusResult.status !== "fulfilled") throw statusResult.reason;
      status = validateStatus(statusResult.value);
      renderStatus(status);
    } catch (error) {
      $("#freshness-title").textContent = "Feed status unavailable";
      $("#last-published").textContent = "A verified publication could not be loaded.";
      $("#source-link").removeAttribute("href");
      $("#source-link").textContent = "Source details unavailable";
      showMessage("The published calendar status could not be loaded. Subscription buttons will appear after a valid feed is published. If this is a local preview, run the publisher and serve its public directory.");
      console.warn("Calendar status:", error);
    }
    try {
      if (scheduleResult.status !== "fulfilled") throw scheduleResult.reason;
      if (!status || scheduleResult.value.season !== status.season || scheduleResult.value.fetched_at !== status.fetched_at) throw new Error("Schedule and status must come from the same publication.");
      renderFixtures(scheduleResult.value);
    } catch (error) {
      $("#fixtures").replaceChildren(node("p", "empty-state", "The schedule preview is unavailable. Reload this page after the next successful publication."));
      console.warn("Calendar preview:", error);
    }
  }
  initialize();
})();
