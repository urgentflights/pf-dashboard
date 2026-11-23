(function () {
  const body = document.body;
  const isAdmin = body.dataset.admin === '1';
  let today = body.dataset.today;
  let trips = [];
  let months = [];
  let tile = '';
  let typeFilter = 'all';
  let query = '';
  let tab = 'board';
  let histQuery = '';
  let histMonth = 'all';
  let histType = 'all';
  let histStatus = 'completed';
  let adding = false;

  const board = document.getElementById('board');
  const meta = document.getElementById('meta');
  const banner = document.getElementById('banner');
  const formWrap = document.getElementById('trip-form-wrap');

  function el(tag, attrs, kids) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(function (pair) {
      const key = pair[0];
      const value = pair[1];
      if (value == null || value === false) return;
      if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = value;
      else if (key === 'html') node.innerHTML = value;
      else node.setAttribute(key, value);
    });
    (kids || []).forEach(function (kid) {
      if (kid) node.append(kid);
    });
    return node;
  }

  function isBlank(value) { return !value || !String(value).trim(); }

  function typeClass(type) {
    const key = String(type || '').replace(/[^a-zA-Z]/g, '');
    if (key === 'Organ' || key === 'AirAmbulance' || key === 'Corporate') return 't-' + key;
    return 't-Other';
  }

  function statusClass(status) {
    const key = String(status || '').toLowerCase().replace(/[^a-z]/g, '');
    if (['quote', 'booked', 'inprogress', 'completed', 'cancelled'].indexOf(key) !== -1) {
      return 's-' + key;
    }
    return 's-other';
  }

  function modeLabel(mode) {
    const key = String(mode || '').toLowerCase().replace(/[^a-z]/g, '');
    if (key === 'commercial') return 'Commercial';
    if (key === 'charter') return 'Charter';
    if (key === 'commobc' || key === 'obc' || key === 'onboardcourier') return 'OBC';
    if (key === 'ground') return 'Ground';
    return mode ? String(mode) : '';
  }

  function isClosed(trip) {
    const status = String(trip.status || '').toLowerCase();
    return status === 'completed' || status === 'cancelled' || status === 'canceled';
  }

  function isQuote(trip) {
    return /^quote$/i.test(trip.status || '');
  }

  function isCommercialFlight(trip) {
    const label = modeLabel(trip.mode);
    return label === 'Commercial' || label === 'OBC';
  }

  function addDays(iso, days) {
    const parts = iso.split('-').map(Number);
    const date = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
    date.setUTCDate(date.getUTCDate() + days);
    return date.toISOString().slice(0, 10);
  }

  function isTodayTrip(trip) {
    return !isClosed(trip) && trip.trip_date === today;
  }

  function isNext3(trip) {
    if (isClosed(trip) || !trip.trip_date) return false;
    return trip.trip_date > today && trip.trip_date <= addDays(today, 3);
  }

  function isOpenQuote(trip) {
    return isQuote(trip) && !isClosed(trip);
  }

  function formatDepTime(value) {
    const raw = String(value || '').trim();
    if (!raw) return '';
    let match = raw.match(/(?:T|\s)(\d{1,2}):(\d{2})(?::\d{2})?/);
    let hour;
    let minute;
    let ampm = null;
    if (match) {
      hour = Number(match[1]);
      minute = match[2];
    } else {
      match = raw.match(/(\d{1,2}):(\d{2})\s*(AM|PM|am|pm)?/);
      if (!match) return 'Dep ' + raw;
      hour = Number(match[1]);
      minute = match[2];
      ampm = match[3] ? match[3].toUpperCase() : null;
    }
    if (ampm) {
      return 'Dep ' + (hour % 12 || 12) + ':' + minute + ' ' + ampm;
    }
    const suffix = hour >= 12 ? 'PM' : 'AM';
    return 'Dep ' + (hour % 12 || 12) + ':' + minute + ' ' + suffix;
  }

  function formatAirport(airport, terminal) {
    const place = String(airport || '').trim();
    let gate = String(terminal || '').trim();
    if (gate && /^\d+[A-Za-z]?$/.test(gate)) gate = 'T' + gate;
    return [place, gate].filter(Boolean).join(' ');
  }

  function flightLine(trip) {
    const airline = String(trip.airline || '').trim();
    const number = String(trip.flight_number || '').trim();
    let flight = [airline, number].filter(Boolean).join(' ');
    if (airline && number && number.toUpperCase().indexOf(airline.toUpperCase()) === 0) {
      flight = number;
    }
    if (!flight) flight = 'Flight TBD';
    const bits = [flight];
    const place = formatAirport(trip.departure_airport, trip.departure_terminal);
    if (place) bits.push(place);
    const dep = formatDepTime(trip.departure_time);
    if (dep) bits.push(dep);
    return bits.join(' · ');
  }

  function prettyDate(iso) {
    if (!iso) return 'No date';
    const parts = iso.split('-').map(Number);
    if (parts.length < 3 || !parts[0]) return iso;
    const date = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    return days[date.getUTCDay()] + ' ' + months[date.getUTCMonth()] + ' ' + date.getUTCDate();
  }

  function shortRange() {
    const start = addDays(today, 1);
    const end = addDays(today, 3);
    return prettyDate(start) + ' – ' + prettyDate(end);
  }

  function stamp(value) {
    if (!value) return '';
    const match = String(value).match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/);
    if (!match) return value;
    return match[1] + ' ' + match[2] + ' UTC';
  }

  function phoneLink(phone) {
    const raw = String(phone).trim();
    const href = 'tel:' + raw.replace(/[^\d+]/g, '');
    return el('a', { href: href, text: raw });
  }

  function haystack(trip) {
    return [
      trip.trip_type, trip.client, trip.trip_date, trip.origin, trip.destination,
      trip.pickup_time, trip.delivery_time, trip.mode, modeLabel(trip.mode),
      trip.operator_aircraft, trip.assigned_to, trip.airline, trip.flight_number,
      trip.departure_time, trip.departure_airport, trip.departure_terminal,
      trip.status, trip.phone, trip.notes, trip.created_by, trip.edited_by,
    ].map(function (part) { return String(part || '').toLowerCase(); }).join(' ');
  }

  function visible() {
    return trips.filter(function (trip) {
      if (isClosed(trip)) return false;
      if (typeFilter !== 'all' && trip.trip_type !== typeFilter) return false;
      if (tile === 'today' && !isTodayTrip(trip)) return false;
      if (tile === 'next' && !isNext3(trip)) return false;
      if (tile === 'quotes' && !isOpenQuote(trip)) return false;
      if (query && haystack(trip).indexOf(query.toLowerCase()) === -1) return false;
      return true;
    });
  }

  function historyTrips() {
    return trips.filter(function (trip) {
      if (!isClosed(trip)) return false;
      const status = String(trip.status || '').toLowerCase();
      if (histStatus === 'completed' && status !== 'completed') return false;
      if (histStatus === 'cancelled' && status !== 'cancelled' && status !== 'canceled') return false;
      if (histType !== 'all' && trip.trip_type !== histType) return false;
      if (histMonth !== 'all' && (trip.trip_date || '').slice(0, 7) !== histMonth) return false;
      if (histQuery && haystack(trip).indexOf(histQuery.toLowerCase()) === -1) return false;
      return true;
    }).sort(function (a, b) {
      const da = a.trip_date || '';
      const db = b.trip_date || '';
      if (da !== db) return db < da ? -1 : 1;
      return (b.edited_at || b.created_at || '') < (a.edited_at || a.created_at || '') ? -1 : 1;
    });
  }

  function timeRow(label, value) {
    return el('div', { class: 'time' }, [
      el('span', { class: 'k', text: label }),
      el('span', { class: 'v', text: value || '—' }),
    ]);
  }

  function card(trip) {
    const classes = ['card', typeClass(trip.trip_type), statusClass(trip.status)];
    if (isQuote(trip) && isBlank(trip.assigned_to)) classes.push('needs-crew');
    const node = el('article', { class: classes.join(' '), 'data-id': trip.id });

    const badges = el('div', { class: 'badges' }, [
      el('span', { class: 'badge ' + typeClass(trip.trip_type), text: trip.trip_type || 'Trip' }),
      trip.mode ? el('span', { class: 'badge m-' + (modeLabel(trip.mode) || 'Other'), text: modeLabel(trip.mode) }) : null,
      el('span', { class: 'badge ' + statusClass(trip.status), text: trip.status || 'No status' }),
    ]);
    node.append(el('div', { class: 'card-top' }, [
      el('div', { class: 'swap', text: trip.client || 'No client' }),
      badges,
    ]));

    node.append(el('p', { class: 'route' }, [
      el('span', { text: trip.origin || '—' }),
      el('span', { class: 'arrow', text: '→' }),
      el('span', { text: trip.destination || '—' }),
    ]));

    node.append(el('div', { class: 'times' }, [
      timeRow('Pickup', trip.pickup_time),
      timeRow('Arrival', trip.delivery_time),
    ]));

    if (isCommercialFlight(trip)) {
      node.append(el('p', { class: 'flight', text: flightLine(trip) }));
    }

    const whoClass = isBlank(trip.assigned_to) && (modeLabel(trip.mode) === 'OBC' || modeLabel(trip.mode) === 'Charter') && !isClosed(trip)
      ? 'who alarm' : 'who';
    const whoName = !isBlank(trip.assigned_to) ? trip.assigned_to : (whoClass.indexOf('alarm') !== -1 ? 'Unassigned' : '—');
    const who = el('div', { class: whoClass }, [
      el('span', { class: 'k', text: 'On this trip' }),
      el('span', { class: 'name', text: whoName }),
    ]);
    if (trip.operator_aircraft) who.append(el('span', { class: 'tail', text: trip.operator_aircraft }));
    node.append(who);

    if (trip.phone) node.append(el('p', { class: 'phone' }, [phoneLink(trip.phone)]));
    if (trip.notes) node.append(el('p', { class: 'notes', text: trip.notes }));
    const stamps = [];
    if (trip.created_by || trip.created_at) {
      stamps.push((trip.created_by ? 'Added by ' + trip.created_by : 'Added') + (trip.created_at ? ' · ' + stamp(trip.created_at) : ''));
    }
    if (trip.edited_by || trip.edited_at) {
      if (trip.edited_at !== trip.created_at || trip.edited_by !== trip.created_by) {
        stamps.push((trip.edited_by ? 'Edited by ' + trip.edited_by : 'Edited') + (trip.edited_at ? ' · ' + stamp(trip.edited_at) : ''));
      }
    }
    if (stamps.length) node.append(el('p', { class: 'stamp', text: stamps.join(' · ') }));

    const actions = [
      el('button', { type: 'button', class: 'ghost', 'data-act': 'edit', text: 'Edit' }),
    ];
    if (!isClosed(trip)) {
      actions.push(el('button', { type: 'button', class: 'ghost', 'data-act': 'cancel-trip', text: 'Cancel trip' }));
    }
    if (isAdmin) {
      actions.push(el('button', { type: 'button', class: 'ghost danger', 'data-act': 'delete', text: 'Delete' }));
    }
    node.append(el('div', { class: 'actions' }, actions));
    return node;
  }

  function selectField(label, name, value, options) {
    const select = el('select', { name: name });
    options.forEach(function (opt) {
      const item = el('option', { value: opt.value, text: opt.label });
      if ((value || '') === opt.value) item.selected = true;
      select.append(item);
    });
    return el('label', { text: label }, [select]);
  }

  function field(label, name, value, placeholder, max, type) {
    const input = el('input', {
      name: name,
      type: type || 'text',
      value: value || '',
      placeholder: placeholder || '',
      maxlength: String(max || 120),
      autocomplete: 'off',
    });
    return el('label', { text: label }, [input]);
  }

  function noteField(value) {
    const input = el('textarea', { name: 'notes', maxlength: '4000', placeholder: 'Notes for the crew' });
    input.value = value || '';
    return el('label', { class: 'span-2', text: 'Notes' }, [input]);
  }

  function toggleFlightFields(form) {
    const mode = (form.querySelector('[name=mode]') || {}).value;
    const show = mode === 'Commercial' || mode === 'OBC';
    const group = form.querySelector('.flight-fields');
    if (group) group.hidden = !show;
  }

  function tripForm(trip, onCancel) {
    const data = trip || {};
    const form = el('form', { class: 'editor trip-editor' });
    const grid = el('div', { class: 'editor-grid' });
    grid.append(
      selectField('Trip type', 'trip_type', data.trip_type, [
        { value: 'Organ', label: 'Organ' },
        { value: 'Air Ambulance', label: 'Air Ambulance' },
        { value: 'Corporate', label: 'Corporate' },
      ]),
      selectField('Status', 'status', data.status || 'Quote', [
        { value: 'Quote', label: 'Quote' },
        { value: 'Booked', label: 'Booked' },
        { value: 'In progress', label: 'In progress' },
        { value: 'Completed', label: 'Completed' },
        { value: 'Cancelled', label: 'Cancelled' },
      ]),
      field('Client / customer', 'client', data.client, 'Who booked this trip', 120),
      field('Trip date', 'trip_date', data.trip_date, 'YYYY-MM-DD', 40, 'date'),
      field('From', 'origin', data.origin, 'Airport or place', 120),
      field('To', 'destination', data.destination, 'Airport or place', 120),
      field('Pickup time', 'pickup_time', data.pickup_time, '10:00 AM ET', 80),
      field('Delivery / arrival', 'delivery_time', data.delivery_time, '2:30 PM ET', 80),
      selectField('Mode', 'mode', data.mode || '', [
        { value: '', label: 'Choose mode' },
        { value: 'Charter', label: 'Charter' },
        { value: 'Commercial', label: 'Commercial' },
        { value: 'OBC', label: 'OBC' },
        { value: 'Ground', label: 'Ground' },
      ]),
      field('Operator / aircraft', 'operator_aircraft', data.operator_aircraft, 'Tail or operator', 80),
      field('Crew / assigned to', 'assigned_to', data.assigned_to, 'Who is on this trip', 120),
      field('Phone', 'phone', data.phone, 'Contact number', 40),
    );
    const flight = el('div', { class: 'flight-fields editor-grid span-2' });
    flight.append(
      field('Airline', 'airline', data.airline, 'AA, Delta…', 40),
      field('Flight number', 'flight_number', data.flight_number, '1234', 40),
      field('Departure time', 'departure_time', data.departure_time, '6:15 AM', 80),
      field('Departure airport', 'departure_airport', data.departure_airport, 'JFK', 40),
      field('Terminal', 'departure_terminal', data.departure_terminal, 'T8', 40),
    );
    grid.append(flight, noteField(data.notes));
    form.append(grid);
    const actions = el('div', { class: 'editor-actions' }, [
      el('button', { type: 'submit', class: 'primary', text: trip ? 'Save' : 'Add trip' }),
      el('button', { type: 'button', class: 'ghost', 'data-act': 'cancel', text: 'Close' }),
    ]);
    const err = el('p', { class: 'form-error', hidden: 'hidden' });
    form.append(actions, err);
    form.addEventListener('change', function (event) {
      if (event.target && event.target.name === 'mode') toggleFlightFields(form);
    });
    form.addEventListener('submit', function (event) {
      event.preventDefault();
      saveForm(form, trip && trip.id, err);
    });
    form.addEventListener('click', function (event) {
      if (event.target.closest('[data-act=cancel]')) {
        event.preventDefault();
        if (onCancel) onCancel();
      }
    });
    toggleFlightFields(form);
    return form;
  }

  function formPayload(form) {
    const data = {};
    Array.from(form.elements).forEach(function (input) {
      if (!input.name) return;
      data[input.name] = input.value;
    });
    return data;
  }

  async function saveForm(form, tripId, err) {
    err.hidden = true;
    const payload = formPayload(form);
    const url = tripId ? '/api/trips/' + encodeURIComponent(tripId) : '/api/trips';
    const method = tripId ? 'PATCH' : 'POST';
    try {
      const response = await fetch(url, {
        method: method,
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify(payload),
      });
      const body = await response.json().catch(function () { return {}; });
      if (!response.ok) {
        err.textContent = body.error || 'Could not save the trip.';
        err.hidden = false;
        return;
      }
      adding = false;
      await load();
    } catch (error) {
      err.textContent = 'Could not save the trip.';
      err.hidden = false;
    }
  }

  function showAddForm() {
    adding = true;
    formWrap.hidden = false;
    formWrap.replaceChildren(el('div', { class: 'card add-card' }, [
      el('h2', { text: 'New trip' }),
      tripForm(null, function () {
        adding = false;
        formWrap.hidden = true;
        formWrap.replaceChildren();
      }),
    ]));
    formWrap.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function renderTiles() {
    document.getElementById('n-today').textContent = String(trips.filter(isTodayTrip).length);
    document.getElementById('n-next').textContent = String(trips.filter(isNext3).length);
    document.getElementById('n-quotes').textContent = String(trips.filter(isOpenQuote).length);
    document.getElementById('hint-next').textContent = shortRange();
    document.querySelectorAll('#tiles button').forEach(function (button) {
      button.setAttribute('aria-pressed', button.getAttribute('data-tile') === tile ? 'true' : 'false');
    });
  }

  function renderBoard() {
    const rows = visible();
    board.replaceChildren();
    renderTiles();
    const openCount = trips.filter(function (trip) { return !isClosed(trip); }).length;
    meta.textContent = rows.length
      + (rows.length === 1 ? ' trip' : ' trips')
      + ' · ' + openCount + ' active';
    if (!trips.length && !adding) {
      board.append(el('p', { class: 'empty', text: 'No trips yet. Add a trip to put it on this board.' }));
      return;
    }
    if (!rows.length) {
      board.append(el('p', { class: 'empty', text: 'No upcoming trips match these filters.' }));
      return;
    }
    let lastDate = null;
    let dateBox = null;
    const perDate = {};
    rows.forEach(function (trip) {
      const key = trip.trip_date || '';
      perDate[key] = (perDate[key] || 0) + 1;
    });
    rows.forEach(function (trip) {
      const dateKey = trip.trip_date || '';
      if (dateKey !== lastDate) {
        lastDate = dateKey;
        const heading = el('div', { class: 'day' }, [
          el('h2', { text: prettyDate(dateKey) }),
          el('span', { class: 'tag', text: perDate[dateKey] + (perDate[dateKey] === 1 ? ' trip' : ' trips') }),
        ]);
        dateBox = el('div', { class: 'stack' });
        board.append(heading, dateBox);
      }
      dateBox.append(card(trip));
    });
  }

  function emptyTableRow(text, cols) {
    const row = el('tr');
    row.append(el('td', { class: 'empty', text: text, colspan: String(cols) }));
    return row;
  }

  function tripRow(trip) {
    const flight = isCommercialFlight(trip) ? flightLine(trip) : (trip.operator_aircraft || '—');
    return el('tr', {}, [
      el('td', { text: trip.trip_date || '—' }),
      el('td', { text: trip.trip_type || '—' }),
      el('td', { text: trip.client || '—' }),
      el('td', { class: 'cell-route', text: (trip.origin || '—') + ' → ' + (trip.destination || '—') }),
      el('td', { text: modeLabel(trip.mode) || '—' }),
      el('td', { text: flight }),
      el('td', { text: trip.status || '—' }),
      el('td', { text: trip.assigned_to || '—' }),
    ]);
  }

  function renderHistoryFilters() {
    const select = document.getElementById('hist-month');
    const current = histMonth;
    const keys = {};
    trips.forEach(function (trip) {
      const key = (trip.trip_date || '').slice(0, 7);
      if (key) keys[key] = true;
    });
    const monthsList = Object.keys(keys).sort().reverse();
    select.replaceChildren(el('option', { value: 'all', text: 'All months' }));
    monthsList.forEach(function (key) {
      const parts = key.split('-');
      const names = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
      const label = names[Number(parts[1]) - 1] + ' ' + parts[0];
      const opt = el('option', { value: key, text: label });
      if (key === current) opt.selected = true;
      select.append(opt);
    });
  }

  function renderMonths() {
    const tbody = document.querySelector('#pf-months tbody');
    tbody.replaceChildren();
    if (!months.length) {
      tbody.append(emptyTableRow('No dated trips yet.', 5));
      return;
    }
    months.forEach(function (row) {
      tbody.append(el('tr', {}, [
        el('td', { text: row.label || row.month }),
        el('td', { text: String(row.Organ || 0) }),
        el('td', { text: String(row['Air Ambulance'] || 0) }),
        el('td', { text: String(row.Corporate || 0) }),
        el('td', { text: String(row.total || 0) }),
      ]));
    });
  }

  function renderHistory() {
    renderHistoryFilters();
    renderMonths();
    const rows = historyTrips();
    const scope = histStatus === 'completed' ? 'completed'
      : (histStatus === 'cancelled' ? 'cancelled' : 'completed or cancelled');
    document.getElementById('hist-meta').textContent = rows.length
      + (rows.length === 1 ? ' trip' : ' trips')
      + ' · ' + scope + ' · newest first';
    const tbody = document.querySelector('#hist-table tbody');
    tbody.replaceChildren();
    if (!rows.length) {
      tbody.append(emptyTableRow('No past trips match these filters.', 8));
    } else {
      rows.forEach(function (trip) { tbody.append(tripRow(trip)); });
    }
  }

  function tabFromHash() {
    const hash = (location.hash || '').replace('#', '').toLowerCase();
    if (hash === 'history') return 'history';
    return 'board';
  }

  function hashForTab(name) {
    return name === 'history' ? '#history' : '#board';
  }

  function showTab(name, updateHash) {
    tab = name === 'history' ? 'history' : 'board';
    document.body.setAttribute('data-tab', tab);
    ['board', 'history'].forEach(function (item) {
      const selected = item === tab;
      document.getElementById('tab-' + item).setAttribute('aria-selected', selected ? 'true' : 'false');
      document.getElementById('panel-' + item).hidden = !selected;
    });
    if (updateHash !== false) {
      const next = hashForTab(tab);
      if (location.hash !== next) window.history.replaceState(null, '', next);
    }
    renderActive();
  }

  function renderActive() {
    if (tab === 'history') renderHistory();
    else if (!document.querySelector('#board .editor')) renderBoard();
  }

  function showBanner(text) {
    if (!text) {
      banner.hidden = true;
      banner.textContent = '';
      return;
    }
    banner.hidden = false;
    banner.textContent = text;
  }

  async function load() {
    try {
      const response = await fetch('/api/trips', { headers: { 'Accept': 'application/json' } });
      if (response.status === 401) {
        location.href = '/login';
        return;
      }
      if (!response.ok) throw new Error('load failed');
      const payload = await response.json();
      trips = payload.trips || [];
      months = payload.months || [];
      if (payload.today) today = payload.today;
      showBanner('');
      renderActive();
    } catch (error) {
      showBanner('Could not load trips. Try refresh.');
    }
  }

  async function cancelTrip(id) {
    if (!window.confirm('Cancel this trip? It will move to History.')) return;
    const response = await fetch('/api/trips/' + encodeURIComponent(id), {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify({ status: 'Cancelled' }),
    });
    if (!response.ok) {
      const body = await response.json().catch(function () { return {}; });
      showBanner(body.error || 'Could not cancel the trip.');
      return;
    }
    await load();
  }

  async function deleteTrip(id) {
    if (!window.confirm('Delete this trip permanently? This cannot be undone.')) return;
    const response = await fetch('/api/trips/' + encodeURIComponent(id), {
      method: 'DELETE',
      headers: { 'Accept': 'application/json' },
    });
    if (response.status === 403) {
      showBanner('Only an admin can delete a trip.');
      return;
    }
    if (!response.ok) {
      const body = await response.json().catch(function () { return {}; });
      showBanner(body.error || 'Could not delete the trip.');
      return;
    }
    await load();
  }

  document.getElementById('tiles').addEventListener('click', function (event) {
    const button = event.target.closest('button');
    if (!button) return;
    const next = button.getAttribute('data-tile');
    tile = tile === next ? '' : next;
    renderBoard();
  });

  document.getElementById('types').addEventListener('click', function (event) {
    const button = event.target.closest('button');
    if (!button) return;
    typeFilter = button.getAttribute('data-type');
    document.querySelectorAll('#types button').forEach(function (item) {
      item.setAttribute('aria-pressed', item === button ? 'true' : 'false');
    });
    renderBoard();
  });

  document.getElementById('q').addEventListener('input', function (event) {
    query = event.target.value.trim();
    renderBoard();
  });

  document.getElementById('add-trip').addEventListener('click', function () {
    showAddForm();
  });

  document.getElementById('refresh').addEventListener('click', function () {
    load();
  });

  document.getElementById('board').addEventListener('click', function (event) {
    const button = event.target.closest('button');
    if (!button) return;
    const article = button.closest('article.card');
    if (!article) return;
    const id = article.getAttribute('data-id');
    const trip = trips.find(function (item) { return item.id === id; });
    if (!trip) return;
    const act = button.getAttribute('data-act');
    if (act === 'edit') {
      article.replaceChildren(tripForm(trip, function () { renderBoard(); }));
    } else if (act === 'cancel-trip') {
      cancelTrip(id);
    } else if (act === 'delete') {
      deleteTrip(id);
    }
  });

  document.querySelector('.tabs').addEventListener('click', function (event) {
    const button = event.target.closest('button');
    if (!button) return;
    const name = button.id === 'tab-history' ? 'history' : 'board';
    showTab(name, true);
  });

  document.getElementById('hist-q').addEventListener('input', function (event) {
    histQuery = event.target.value.trim();
    renderHistory();
  });

  document.getElementById('hist-month').addEventListener('change', function (event) {
    histMonth = event.target.value;
    renderHistory();
  });

  document.getElementById('hist-types').addEventListener('click', function (event) {
    const button = event.target.closest('button');
    if (!button) return;
    histType = button.getAttribute('data-hist-type');
    document.querySelectorAll('#hist-types button').forEach(function (item) {
      item.setAttribute('aria-pressed', item === button ? 'true' : 'false');
    });
    renderHistory();
  });

  document.getElementById('hist-status').addEventListener('click', function (event) {
    const button = event.target.closest('button');
    if (!button) return;
    histStatus = button.getAttribute('data-hist-status');
    document.querySelectorAll('#hist-status button').forEach(function (item) {
      item.setAttribute('aria-pressed', item === button ? 'true' : 'false');
    });
    renderHistory();
  });

  window.addEventListener('hashchange', function () {
    showTab(tabFromHash(), false);
  });

  tab = tabFromHash();
  showTab(tab, false);

  setInterval(function () {
    if (document.visibilityState === 'hidden') return;
    if (document.querySelector('.editor')) return;
    load();
  }, 60000);

  load();
})();
