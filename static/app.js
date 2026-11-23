(function () {
  const body = document.body;
  let today = body.dataset.today;
  let moves = [];
  let history = false;
  let tile = '';
  let typeFilter = 'all';
  let statusFilter = 'all';
  let query = '';
  let tab = 'board';
  let nkrWeekStart = null;
  let nkrShowRemoved = false;
  let histQuery = '';
  let histMonth = 'all';
  let histType = 'all';
  let histCenter = 'all';
  let histStatus = 'completed';

  const board = document.getElementById('board');
  const meta = document.getElementById('meta');
  const banner = document.getElementById('banner');
  const historyBtn = document.getElementById('history');

  function el(tag, attrs, kids) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(function (pair) {
      const key = pair[0];
      const value = pair[1];
      if (value == null || value === false) return;
      if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = value;
      else node.setAttribute(key, value);
    });
    (kids || []).forEach(function (kid) {
      if (kid) node.append(kid);
    });
    return node;
  }

  function methodLabel(method) {
    const key = String(method || '').toLowerCase().replace(/[^a-z]/g, '');
    if (key === 'commercial') return 'Commercial';
    if (key === 'charter') return 'Charter';
    if (key === 'commobc' || key === 'obc' || key === 'onboardcourier') return 'OBC';
    if (key === 'ground') return 'Ground';
    if (key === 'internal') return 'Internal';
    return method ? String(method) : 'Other';
  }

  function methodClass(method) {
    const label = methodLabel(method);
    if (['Commercial', 'Charter', 'OBC', 'Ground', 'Internal'].indexOf(label) === -1) return 'm-Other';
    return 'm-' + label;
  }

  function statusClass(status) {
    const key = String(status || '').toLowerCase();
    if (key === 'scheduled' || key === 'completed' || key === 'removed') return 's-' + key;
    return 's-other';
  }

  function isRemoved(move) { return /^removed$/i.test(move.status || ''); }
  function isCompleted(move) { return /^completed$/i.test(move.status || ''); }
  function isBlank(value) { return !value || !String(value).trim(); }

  function isInHouse(move) {
    const label = methodLabel(move.method);
    return label === 'OBC' || label === 'Charter';
  }

  function needsCrew(move) {
    return isInHouse(move) && isBlank(move.assigned_to) && !isRemoved(move);
  }

  function addDays(iso, days) {
    const parts = iso.split('-').map(Number);
    const date = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
    date.setUTCDate(date.getUTCDate() + days);
    return date.toISOString().slice(0, 10);
  }

  function isTodayMove(move) {
    return !isRemoved(move) && move.pickup_date === today;
  }

  function isNext3(move) {
    if (isRemoved(move) || !move.pickup_date) return false;
    return move.pickup_date > today && move.pickup_date <= addDays(today, 3);
  }

  function isOpen(move) {
    if (!needsCrew(move) || isCompleted(move)) return false;
    if (!move.pickup_date) return true;
    return move.pickup_date >= today;
  }

  function haystack(move) {
    return [
      move.swap_id, move.donor, move.recipient, move.method, methodLabel(move.method),
      move.pickup, move.delivery, move.status, move.assigned_to, move.aircraft, move.phone,
      move.notes, move.airline, move.flight_number, move.departure_time,
      move.departure_airport, move.departure_terminal,
      move.airspace_driver, move.airspace_flight, move.airspace_awb,
      move.airspace_order_id, move.airspace_status,
    ].map(function (value) { return String(value || '').toLowerCase(); }).join('\n');
  }

  function visible() {
    const tokens = query.toLowerCase().split(/\s+/).filter(Boolean);
    return moves.filter(function (move) {
      const dated = move.pickup_date || '';
      if (history) {
        if (!dated || dated >= today) return false;
      } else if (dated && dated < today) {
        return false;
      }
      if (tile === 'today' && !isTodayMove(move)) return false;
      if (tile === 'next' && !isNext3(move)) return false;
      if (tile === 'open' && !isOpen(move)) return false;
      if (typeFilter !== 'all' && methodLabel(move.method) !== typeFilter) return false;
      if (statusFilter !== 'all' && String(move.status || '').toLowerCase() !== statusFilter.toLowerCase()) return false;
      if (tokens.length) {
        const hay = haystack(move);
        if (!tokens.every(function (token) { return hay.indexOf(token) !== -1; })) return false;
      }
      return true;
    }).sort(function (a, b) {
      const da = a.pickup_date || '9999-99-99';
      const db = b.pickup_date || '9999-99-99';
      if (da !== db) {
        if (history) return da < db ? 1 : -1;
        return da < db ? -1 : 1;
      }
      return String(a.swap_id).localeCompare(String(b.swap_id), 'en', { numeric: true });
    });
  }

  function dateTitle(iso) {
    if (!iso) return 'No pickup date';
    const parts = iso.split('-').map(Number);
    const date = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
    return date.toLocaleDateString('en-US', {
      weekday: 'long', month: 'long', day: 'numeric', year: 'numeric', timeZone: 'UTC',
    });
  }

  function dateTag(iso) {
    if (!iso) return '';
    if (iso === today) return 'Today';
    if (iso === addDays(today, 1)) return 'Tomorrow';
    return '';
  }

  function shortRange() {
    const start = addDays(today, 1);
    const end = addDays(today, 3);
    const fmt = function (iso) {
      const parts = iso.split('-').map(Number);
      const date = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
      return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' });
    };
    return fmt(start) + ' – ' + fmt(end);
  }

  function stamp(iso) {
    if (!iso) return '';
    const date = new Date(iso);
    if (isNaN(date.getTime())) return iso;
    return date.toLocaleString('en-US', {
      timeZone: 'America/New_York', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
    }) + ' ET';
  }

  function phoneLink(phone) {
    if (!/^[0-9+().\-\s]+$/.test(phone)) return el('span', { text: phone });
    const href = 'tel:' + phone.replace(/[^\d+]/g, '');
    return el('a', { href: href, text: phone });
  }

  function card(move) {
    const label = methodLabel(move.method);
    const classes = ['card', methodClass(move.method), statusClass(move.status)];
    if (needsCrew(move)) classes.push('needs-crew');
    const node = el('article', { class: classes.join(' '), 'data-id': move.swap_id });

    const badges = el('div', { class: 'badges' }, [
      el('span', { class: 'badge ' + methodClass(move.method), text: label }),
      el('span', { class: 'badge ' + statusClass(move.status), text: move.status || 'No status' }),
    ]);
    node.append(el('div', { class: 'card-top' }, [
      el('div', { class: 'swap', text: move.swap_id }),
      badges,
    ]));

    node.append(el('p', { class: 'route' }, [
      el('span', { text: move.donor || '—' }),
      el('span', { class: 'arrow', text: '→' }),
      el('span', { text: move.recipient || '—' }),
    ]));

    node.append(el('div', { class: 'times' }, [
      timeRow('Pickup', move.pickup),
      timeRow('Delivery', move.delivery),
    ]));

    if (isCommercialFlight(move)) {
      node.append(el('p', { class: 'flight', text: flightLine(move) }));
    }

    const whoClass = needsCrew(move) ? 'who alarm' : 'who';
    const whoName = !isBlank(move.assigned_to) ? move.assigned_to : (needsCrew(move) ? 'Unassigned' : '—');
    const who = el('div', { class: whoClass }, [
      el('span', { class: 'k', text: 'On this trip' }),
      el('span', { class: 'name', text: whoName }),
    ]);
    if (move.aircraft) who.append(el('span', { class: 'tail', text: move.aircraft }));
    node.append(who);

    if (move.phone) node.append(el('p', { class: 'phone' }, [phoneLink(move.phone)]));

    const air = airLine(move);
    if (air) node.append(el('p', { class: 'air', text: air }));
    if (move.notes) node.append(el('p', { class: 'notes', text: move.notes }));
    if (move.edited_by || move.edited_at) {
      const whoEdited = move.edited_by ? 'Edited by ' + move.edited_by : 'Edited';
      const when = move.edited_at ? ' · ' + stamp(move.edited_at) : '';
      node.append(el('p', { class: 'stamp', text: whoEdited + when }));
    }

    node.append(el('div', { class: 'actions' }, [
      el('button', { type: 'button', class: 'ghost', 'data-act': 'edit', text: 'Edit' }),
    ]));
    return node;
  }

  function timeRow(label, value) {
    return el('div', { class: 'time' }, [
      el('span', { class: 'k', text: label }),
      el('span', { class: 'v', text: value || '—' }),
    ]);
  }

  function isCommercialFlight(move) {
    const label = methodLabel(move.method);
    return label === 'Commercial' || label === 'OBC';
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

  function flightLine(move) {
    const airline = String(move.airline || '').trim();
    const number = String(move.flight_number || '').trim();
    let flight = [airline, number].filter(Boolean).join(' ');
    if (airline && number && number.toUpperCase().indexOf(airline.toUpperCase()) === 0) {
      flight = number;
    }
    if (!flight) flight = 'Flight TBD';
    const bits = [flight];
    const place = formatAirport(move.departure_airport, move.departure_terminal);
    if (place) bits.push(place);
    const dep = formatDepTime(move.departure_time);
    if (dep) bits.push(dep);
    return bits.join(' · ');
  }

  function airLine(move) {
    const bits = [];
    if (move.airspace_driver) bits.push(move.airspace_driver);
    if (move.airspace_flight) bits.push(move.airspace_flight);
    if (move.airspace_awb) bits.push('AWB ' + move.airspace_awb);
    if (move.airspace_order_id) bits.push('Order ' + move.airspace_order_id);
    if (move.airspace_status) bits.push(move.airspace_status);
    if (!bits.length) return '';
    return 'Airspace · ' + bits.join(' · ');
  }

  function editor(move) {
    const form = el('form', { class: 'editor' });
    form.append(
      field('Assigned to', 'assigned_to', move.assigned_to, 'Who is on this trip', 120),
      field('Aircraft / tail', 'aircraft', move.aircraft, 'Tail for a charter', 40),
      field('Phone', 'phone', move.phone, 'Contact number', 40),
      field('Airline', 'airline', move.airline, 'AA, Delta…', 40),
      field('Flight number', 'flight_number', move.flight_number, '1234', 40),
      field('Departure time', 'departure_time', move.departure_time, '6:15 AM or 2026-11-24T06:15', 80),
      field('Departure airport', 'departure_airport', move.departure_airport, 'JFK', 40),
      field('Departure terminal', 'departure_terminal', move.departure_terminal, 'T8', 40),
      noteField(move.notes),
    );
    const actions = el('div', { class: 'editor-actions' }, [
      el('button', { type: 'submit', class: 'primary', text: 'Save' }),
      el('button', { type: 'button', class: 'ghost', 'data-act': 'cancel', text: 'Cancel' }),
    ]);
    const err = el('p', { class: 'form-error', hidden: 'hidden' });
    form.append(actions, err);
    form.addEventListener('submit', function (event) {
      event.preventDefault();
      save(form, move.swap_id);
    });
    form.addEventListener('click', function (event) {
      if (event.target.closest('[data-act=cancel]')) {
        event.preventDefault();
        renderBoard();
      }
    });
    return form;
  }

  function field(label, name, value, placeholder, max) {
    const input = el('input', {
      name: name, value: value || '', placeholder: placeholder, maxlength: String(max), autocomplete: 'off',
    });
    return el('label', { text: label }, [input]);
  }

  function noteField(value) {
    const input = el('textarea', { name: 'notes', maxlength: '4000', placeholder: 'Notes for the crew' });
    input.value = value || '';
    return el('label', { text: 'Notes' }, [input]);
  }

  function renderTiles() {
    document.getElementById('n-today').textContent = String(moves.filter(isTodayMove).length);
    document.getElementById('n-next').textContent = String(moves.filter(isNext3).length);
    document.getElementById('n-open').textContent = String(moves.filter(isOpen).length);
    document.getElementById('hint-next').textContent = shortRange();
    document.querySelectorAll('#tiles button').forEach(function (button) {
      button.setAttribute('aria-pressed', button.getAttribute('data-tile') === tile ? 'true' : 'false');
    });
  }

  function renderBoard() {
    const rows = visible();
    board.replaceChildren();
    if (!moves.length) {
      board.append(el('p', { class: 'empty', text: 'No moves yet. Legs show up here after the ingest job posts them.' }));
      return;
    }
    if (!rows.length) {
      board.append(el('p', { class: 'empty', text: history
        ? 'Nothing in history matches these filters.'
        : 'No upcoming legs match these filters.' }));
      return;
    }
    let lastDate = null;
    let lastSwap = null;
    let dateBox = null;
    const perDate = {};
    rows.forEach(function (move) {
      const key = move.pickup_date || '';
      perDate[key] = (perDate[key] || 0) + 1;
    });
    const swapCounts = {};
    rows.forEach(function (move) {
      const key = (move.pickup_date || '') + '|' + String(move.swap_id || '').split('/')[0];
      swapCounts[key] = (swapCounts[key] || 0) + 1;
    });
    rows.forEach(function (move) {
      const dateKey = move.pickup_date || '';
      if (dateKey !== lastDate) {
        const removedHere = rows.filter(function (move) {
          return (move.pickup_date || '') === dateKey && isRemoved(move);
        }).length;
        const total = perDate[dateKey];
        const active = total - removedHere;
        let countText;
        if (removedHere && active) {
          countText = active + ' active · ' + removedHere + ' removed';
        } else if (removedHere) {
          countText = removedHere + ' removed';
        } else {
          countText = total + (total === 1 ? ' leg' : ' legs');
        }
        const bits = [];
        if (dateTag(dateKey)) bits.push(dateTag(dateKey));
        bits.push(countText);
        const head = el('div', { class: 'day' }, [
          el('h2', { text: dateTitle(dateKey) }),
          el('span', { class: 'tag', text: bits.join(' · ') }),
        ]);
        board.append(head);
        dateBox = el('div', { class: 'stack' });
        board.append(dateBox);
        lastDate = dateKey;
        lastSwap = null;
      }
      const root = String(move.swap_id || '').split('/')[0];
      const cluster = dateKey + '|' + root;
      if (root !== lastSwap && swapCounts[cluster] > 1) {
        dateBox.append(el('p', { class: 'swap-label', text: 'Swap ' + root }));
        lastSwap = root;
      } else if (root !== lastSwap) {
        lastSwap = root;
      }
      dateBox.append(card(move));
    });
  }

  function syncHistory() {
    historyBtn.setAttribute('aria-pressed', history ? 'true' : 'false');
    historyBtn.textContent = history ? 'Past dates on' : 'Past dates';
  }

  async function save(form, id) {
    const body = { swap_id: id };
    ['assigned_to', 'aircraft', 'phone', 'airline', 'flight_number',
      'departure_time', 'departure_airport', 'departure_terminal', 'notes'].forEach(function (name) {
      body[name] = form.querySelector('[name="' + name + '"]').value;
    });
    const button = form.querySelector('button[type=submit]');
    button.disabled = true;
    let response;
    try {
      response = await fetch('/api/moves', {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify(body),
      });
    } catch (err) {
      button.disabled = false;
      showFormError(form, 'Save failed. Check the connection and try again.');
      return;
    }
    if (response.status === 401) {
      location.href = '/login';
      return;
    }
    const data = await response.json().catch(function () { return {}; });
    if (!response.ok) {
      button.disabled = false;
      showFormError(form, data.error || 'Save failed');
      return;
    }
    const index = moves.findIndex(function (move) { return move.swap_id === id; });
    if (index >= 0) moves[index] = data.move;
    renderTiles();
    renderActive();
  }

  function showFormError(form, message) {
    const node = form.querySelector('.form-error');
    node.hidden = false;
    node.textContent = message;
  }

  async function load() {
    banner.hidden = true;
    try {
      const response = await fetch('/api/moves', { headers: { 'Accept': 'application/json' } });
      if (response.status === 401) {
        location.href = '/login';
        return;
      }
      if (!response.ok) throw new Error('status ' + response.status);
      const data = await response.json();
      today = data.today || today;
      moves = data.moves || [];
      const clock = new Date().toLocaleTimeString('en-US', {
        timeZone: 'America/New_York', hour: 'numeric', minute: '2-digit',
      });
      meta.textContent = 'Updated ' + clock + ' ET · ' + moves.length + ' legs';
      if (!nkrWeekStart) nkrWeekStart = weekStartSunday(today);
      renderTiles();
      renderActive();
    } catch (err) {
      banner.hidden = false;
      banner.textContent = 'Could not load moves. Check the connection and refresh.';
    }
  }


  const COUNT_METHODS = ['Commercial', 'Charter', 'OBC', 'Ground', 'Internal'];

  function utcDate(iso) {
    const parts = String(iso).split('-').map(Number);
    return new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
  }

  function weekStartSunday(iso) {
    if (!iso) return '';
    const date = utcDate(iso);
    date.setUTCDate(date.getUTCDate() - date.getUTCDay());
    return date.toISOString().slice(0, 10);
  }

  function weekEndSaturday(start) {
    return addDays(start, 6);
  }

  function weekLabel(start) {
    if (!start) return '';
    const endDate = utcDate(weekEndSaturday(start));
    const startDate = utcDate(start);
    const sm = startDate.toLocaleDateString('en-US', { month: 'short', timeZone: 'UTC' });
    const em = endDate.toLocaleDateString('en-US', { month: 'short', timeZone: 'UTC' });
    if (sm === em) return sm + ' ' + startDate.getUTCDate() + '–' + endDate.getUTCDate();
    return sm + ' ' + startDate.getUTCDate() + '–' + em + ' ' + endDate.getUTCDate();
  }

  function shortDate(iso) {
    if (!iso) return '—';
    return utcDate(iso).toLocaleDateString('en-US', {
      weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC',
    });
  }

  function monthTitle(yearMonth) {
    const parts = String(yearMonth).split('-').map(Number);
    const date = new Date(Date.UTC(parts[0], parts[1] - 1, 1));
    return date.toLocaleDateString('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' });
  }

  function emptyCounts() {
    const counts = { Other: 0, removed: 0, total: 0 };
    COUNT_METHODS.forEach(function (name) { counts[name] = 0; });
    return counts;
  }

  function addCount(bucket, move) {
    const label = methodLabel(move.method);
    if (COUNT_METHODS.indexOf(label) !== -1) bucket[label] += 1;
    else bucket.Other += 1;
    bucket.total += 1;
    if (isRemoved(move)) bucket.removed += 1;
  }

  function datedMoves() {
    return moves.filter(function (move) { return !!(move.pickup_date || '').trim(); });
  }

  function weekRangeBounds() {
    const starts = datedMoves().map(function (move) { return weekStartSunday(move.pickup_date); });
    const current = weekStartSunday(today);
    starts.push(current);
    starts.sort();
    return { min: starts[0], max: starts[starts.length - 1], current: current };
  }

  function inWeek(move, start) {
    const date = move.pickup_date || '';
    if (!date || !start) return false;
    return date >= start && date <= weekEndSaturday(start);
  }

  function flightCell(move) {
    if (isCommercialFlight(move) || !isBlank(move.airline) || !isBlank(move.flight_number)) {
      return flightLine(move);
    }
    return '—';
  }

  function assignedCell(move) {
    return isBlank(move.assigned_to) ? '—' : move.assigned_to;
  }

  function emptyTableRow(message, cols) {
    const tr = el('tr', { class: 'empty-row' });
    tr.append(el('td', { text: message, colspan: String(cols), 'data-label': '' }));
    return tr;
  }

  function moveRow(move) {
    const cells = [
      [shortDate(move.pickup_date), 'Date', ''],
      [move.swap_id || '—', 'Swap #', 'cell-swap'],
      [(move.donor || '—') + ' → ' + (move.recipient || '—'), 'Donor to recipient', 'cell-route'],
      [methodLabel(move.method), 'Type', ''],
      [move.pickup || '—', 'Pickup', ''],
      [move.delivery || '—', 'Delivery', ''],
      [flightCell(move), 'Flight', 'cell-flight'],
      [move.status || '—', 'Status', ''],
      [assignedCell(move), 'Assigned', ''],
    ];
    const tr = el('tr', { class: isRemoved(move) ? 'removed' : '' });
    cells.forEach(function (cell) {
      const td = el('td', { 'data-label': cell[1], text: cell[0] });
      if (cell[2]) td.className = cell[2];
      tr.append(td);
    });
    return tr;
  }

  function weekRows() {
    const start = nkrWeekStart || weekStartSunday(today);
    return datedMoves().filter(function (move) {
      if (!inWeek(move, start)) return false;
      if (isRemoved(move) && !nkrShowRemoved) return false;
      return true;
    }).sort(function (a, b) {
      if (a.pickup_date !== b.pickup_date) return a.pickup_date < b.pickup_date ? -1 : 1;
      return String(a.swap_id).localeCompare(String(b.swap_id), 'en', { numeric: true });
    });
  }

  function renderNkr() {
    if (!nkrWeekStart) nkrWeekStart = weekStartSunday(today);
    const bounds = weekRangeBounds();
    const start = nkrWeekStart;
    const label = weekLabel(start);
    const nav = document.getElementById('nkr-week');
    nav.replaceChildren();
    const prev = el('button', { type: 'button', class: 'ghost', id: 'nkr-prev', 'aria-label': 'Previous week', text: 'Prev' });
    const next = el('button', { type: 'button', class: 'ghost', id: 'nkr-next', 'aria-label': 'Next week', text: 'Next' });
    const jump = el('button', { type: 'button', class: 'ghost', id: 'nkr-today', text: 'This week' });
    if (start <= bounds.min) prev.setAttribute('disabled', 'disabled');
    if (start >= bounds.max) next.setAttribute('disabled', 'disabled');
    if (start === bounds.current) jump.hidden = true;
    nav.append(prev, el('h2', { text: label }), next, jump);

    const rows = weekRows();
    const counts = emptyCounts();
    rows.forEach(function (move) { addCount(counts, move); });

    const tiles = document.getElementById('nkr-tiles');
    tiles.replaceChildren();
    COUNT_METHODS.forEach(function (name) {
      tiles.append(el('div', { class: 'tile' }, [
        el('span', { class: 'num', text: String(counts[name]) }),
        el('span', { class: 'label', text: name }),
      ]));
    });

    const removedNote = nkrShowRemoved && counts.removed
      ? ' · ' + counts.removed + ' removed'
      : '';
    document.getElementById('nkr-meta').textContent = counts.total
      + (counts.total === 1 ? ' move' : ' moves')
      + ' in the week of ' + label + removedNote + '. Sunday–Saturday, Eastern.';

    const tbody = document.querySelector('#nkr-table tbody');
    tbody.replaceChildren();
    if (!rows.length) {
      tbody.append(emptyTableRow(
        nkrShowRemoved ? 'No moves in this week.' : 'No moves in this week (removed are hidden).',
        9,
      ));
    } else {
      rows.forEach(function (move) { tbody.append(moveRow(move)); });
    }
    renderMonths();
  }

  function renderMonths() {
    const buckets = {};
    datedMoves().forEach(function (move) {
      if (isRemoved(move) && !nkrShowRemoved) return;
      const key = move.pickup_date.slice(0, 7);
      if (!buckets[key]) buckets[key] = emptyCounts();
      addCount(buckets[key], move);
    });
    const keys = Object.keys(buckets).sort();
    const tbody = document.querySelector('#nkr-months tbody');
    tbody.replaceChildren();
    let tfoot = document.querySelector('#nkr-months tfoot');
    if (!tfoot) {
      tfoot = el('tfoot');
      document.getElementById('nkr-months').append(tfoot);
    }
    tfoot.replaceChildren();
    if (!keys.length) {
      tbody.append(emptyTableRow('No monthly totals yet.', 7));
      return;
    }
    const grand = emptyCounts();
    const labels = ['Month', 'Commercial', 'Charter', 'OBC', 'Ground', 'Internal', 'Total'];
    keys.forEach(function (key) {
      const bucket = buckets[key];
      COUNT_METHODS.forEach(function (name) { grand[name] += bucket[name]; });
      grand.total += bucket.total;
      grand.removed += bucket.removed;
      const values = [monthTitle(key), bucket.Commercial, bucket.Charter, bucket.OBC, bucket.Ground, bucket.Internal, bucket.total];
      const tr = el('tr');
      values.forEach(function (value, i) {
        tr.append(el('td', { 'data-label': labels[i], text: String(value) }));
      });
      tbody.append(tr);
    });
    const foot = el('tr');
    [ 'All months', grand.Commercial, grand.Charter, grand.OBC, grand.Ground, grand.Internal, grand.total ].forEach(function (value, i) {
      foot.append(el('td', { 'data-label': labels[i], text: String(value) }));
    });
    tfoot.append(foot);
  }

  function historySource() {
    return moves.filter(function (move) { return isCompleted(move) || isRemoved(move); });
  }

  function historyMoves() {
    return historySource().filter(function (move) {
      if (histStatus === 'completed' && !isCompleted(move)) return false;
      if (histStatus === 'removed' && !isRemoved(move)) return false;
      if (histMonth !== 'all' && (move.pickup_date || '').slice(0, 7) !== histMonth) return false;
      if (histType !== 'all' && methodLabel(move.method) !== histType) return false;
      if (histCenter !== 'all' && move.donor !== histCenter && move.recipient !== histCenter) return false;
      const tokens = histQuery.toLowerCase().split(/\s+/).filter(Boolean);
      if (tokens.length) {
        const hay = haystack(move);
        if (!tokens.every(function (token) { return hay.indexOf(token) !== -1; })) return false;
      }
      return true;
    }).sort(function (a, b) {
      const da = a.pickup_date || '';
      const db = b.pickup_date || '';
      if (da !== db) return da < db ? 1 : -1;
      return String(a.swap_id).localeCompare(String(b.swap_id), 'en', { numeric: true });
    });
  }

  function renderHistoryFilters() {
    const monthSelect = document.getElementById('hist-month');
    const centerSelect = document.getElementById('hist-center');
    const past = historySource();
    const months = Array.from(new Set(past.map(function (move) {
      return (move.pickup_date || '').slice(0, 7);
    }).filter(Boolean))).sort().reverse();
    const centers = Array.from(new Set(past.flatMap(function (move) {
      return [move.donor, move.recipient];
    }).filter(function (name) { return !isBlank(name); }))).sort(function (a, b) {
      return a.localeCompare(b, 'en', { sensitivity: 'base' });
    });

    const prevMonth = histMonth;
    monthSelect.replaceChildren(el('option', { value: 'all', text: 'All months' }));
    months.forEach(function (yearMonth) {
      monthSelect.append(el('option', { value: yearMonth, text: monthTitle(yearMonth) }));
    });
    monthSelect.value = (prevMonth === 'all' || months.indexOf(prevMonth) !== -1) ? prevMonth : 'all';
    histMonth = monthSelect.value;

    const prevCenter = histCenter;
    centerSelect.replaceChildren(el('option', { value: 'all', text: 'All centers' }));
    centers.forEach(function (name) {
      centerSelect.append(el('option', { value: name, text: name }));
    });
    centerSelect.value = (prevCenter === 'all' || centers.indexOf(prevCenter) !== -1) ? prevCenter : 'all';
    histCenter = centerSelect.value;
  }

  function renderHistory() {
    renderHistoryFilters();
    const rows = historyMoves();
    const scope = histStatus === 'completed' ? 'completed'
      : (histStatus === 'removed' ? 'removed' : 'completed or removed');
    document.getElementById('hist-meta').textContent = rows.length
      + (rows.length === 1 ? ' move' : ' moves')
      + ' · ' + scope + ' · newest first';
    const tbody = document.querySelector('#hist-table tbody');
    tbody.replaceChildren();
    if (!rows.length) {
      tbody.append(emptyTableRow('No past moves match these filters.', 9));
    } else {
      rows.forEach(function (move) { tbody.append(moveRow(move)); });
    }
  }

  function tabFromHash() {
    const hash = (location.hash || '').replace('#', '').toLowerCase();
    if (hash === 'nkr' || hash === 'nkr-moves') return 'nkr';
    if (hash === 'history') return 'history';
    return 'board';
  }

  function hashForTab(name) {
    if (name === 'nkr') return '#nkr';
    if (name === 'history') return '#history';
    return '#board';
  }

  function showTab(name, updateHash) {
    tab = name === 'nkr' || name === 'history' ? name : 'board';
    document.body.setAttribute('data-tab', tab);
    ['board', 'nkr', 'history'].forEach(function (item) {
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
    if (tab === 'nkr') renderNkr();
    else if (tab === 'history') renderHistory();
    else if (!document.querySelector('.editor')) renderBoard();
  }

  document.getElementById('tiles').addEventListener('click', function (event) {
    const button = event.target.closest('button');
    if (!button) return;
    const next = button.getAttribute('data-tile');
    tile = tile === next ? '' : next;
    if (tile) history = false;
    syncHistory();
    renderTiles();
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

  document.getElementById('statuses').addEventListener('click', function (event) {
    const button = event.target.closest('button');
    if (!button) return;
    statusFilter = button.getAttribute('data-status');
    document.querySelectorAll('#statuses button').forEach(function (item) {
      item.setAttribute('aria-pressed', item === button ? 'true' : 'false');
    });
    renderBoard();
  });

  document.getElementById('q').addEventListener('input', function (event) {
    query = event.target.value.trim();
    renderBoard();
  });

  historyBtn.addEventListener('click', function () {
    history = !history;
    if (history) tile = '';
    syncHistory();
    renderTiles();
    renderBoard();
  });

  document.getElementById('refresh').addEventListener('click', load);

  board.addEventListener('click', function (event) {
    const button = event.target.closest('[data-act=edit]');
    if (!button) return;
    const cardNode = button.closest('.card');
    const id = cardNode.getAttribute('data-id');
    const move = moves.find(function (item) { return item.swap_id === id; });
    if (!move) return;
    const actions = cardNode.querySelector('.actions');
    actions.replaceWith(editor(move));
    const input = cardNode.querySelector('input');
    if (input) input.focus();
  });


  document.querySelector('.tabs').addEventListener('click', function (event) {
    const button = event.target.closest('[role=tab]');
    if (!button) return;
    showTab(button.id.replace('tab-', ''));
  });

  document.getElementById('nkr-week').addEventListener('click', function (event) {
    const button = event.target.closest('button');
    if (!button || button.disabled) return;
    const bounds = weekRangeBounds();
    if (button.id === 'nkr-prev' && nkrWeekStart > bounds.min) {
      nkrWeekStart = addDays(nkrWeekStart, -7);
    } else if (button.id === 'nkr-next' && nkrWeekStart < bounds.max) {
      nkrWeekStart = addDays(nkrWeekStart, 7);
    } else if (button.id === 'nkr-today') {
      nkrWeekStart = bounds.current;
    } else {
      return;
    }
    renderNkr();
  });

  document.getElementById('nkr-removed').addEventListener('change', function (event) {
    nkrShowRemoved = event.target.checked;
    renderNkr();
  });

  document.getElementById('hist-q').addEventListener('input', function (event) {
    histQuery = event.target.value.trim();
    renderHistory();
  });

  document.getElementById('hist-month').addEventListener('change', function (event) {
    histMonth = event.target.value;
    renderHistory();
  });

  document.getElementById('hist-center').addEventListener('change', function (event) {
    histCenter = event.target.value;
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
