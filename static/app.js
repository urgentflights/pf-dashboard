(function () {
  const body = document.body;
  let today = body.dataset.today;
  let moves = [];
  let history = false;
  let tile = '';
  let typeFilter = 'all';
  let statusFilter = 'all';
  let query = '';

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
      move.notes, move.airspace_driver, move.airspace_flight, move.airspace_awb,
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
    historyBtn.textContent = history ? 'History on' : 'History';
  }

  async function save(form, id) {
    const body = { swap_id: id };
    ['assigned_to', 'aircraft', 'phone', 'notes'].forEach(function (name) {
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
    renderBoard();
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
      renderTiles();
      if (!document.querySelector('.editor')) renderBoard();
    } catch (err) {
      banner.hidden = false;
      banner.textContent = 'Could not load moves. Check the connection and refresh.';
    }
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

  setInterval(function () {
    if (document.visibilityState === 'hidden') return;
    if (document.querySelector('.editor')) return;
    load();
  }, 60000);

  load();
})();
