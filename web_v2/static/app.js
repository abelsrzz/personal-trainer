/* RunPilot Next — app.js */
(function () {
  'use strict';

  const cfg = document.getElementById('app-config');
  if (!cfg) return;

  const url = (attr) => cfg.dataset[attr] || '';

  /* ── Garmin sync ─────────────────────────────────── */
  (function garminSync() {
    const button = document.querySelector('[data-garmin-sync-button]');
    const label  = document.querySelector('[data-garmin-sync-label]');
    const form   = document.querySelector('[data-garmin-sync-form]');
    if (!button || !form) return;

    const renderState = (sync) => {
      const isRunning = Boolean(sync && sync.running);
      const isOk      = sync && sync.last_ok === true;
      const isError   = sync && sync.last_ok === false;
      button.disabled = isRunning;
      button.classList.toggle('is-running', isRunning);
      button.classList.toggle('is-ok',      !isRunning && isOk);
      button.classList.toggle('is-error',   !isRunning && isError);
      if (label) label.textContent = isRunning ? 'Sincronizando…' : 'Garmin';
    };

    const refreshStatus = async () => {
      try {
        const r = await fetch(url('garminSyncUrl'), { credentials: 'same-origin' });
        if (!r.ok) return;
        const p = await r.json();
        if (p && p.ok) renderState(p.sync || {});
      } catch (_) {}
    };

    form.addEventListener('submit', () => renderState({ running: true }));
    refreshStatus();
    window.setInterval(refreshStatus, 10000);
  })();

  /* ── Planner busy overlay + modals ──────────────── */
  (function plannerModals() {
    const busyOverlay  = document.querySelector('[data-planner-busy]');
    const busyTitle    = document.querySelector('[data-planner-busy-title]');
    const busyMessage  = document.querySelector('[data-planner-busy-message]');
    const modalTriggers = document.querySelectorAll('[data-modal-open]');
    const modalClosers  = document.querySelectorAll('[data-modal-close]');
    const modalShells   = document.querySelectorAll('[data-modal-shell]');
    const plannerForms  = document.querySelectorAll('[data-planner-form]');

    const closeModal = (shell) => {
      if (!shell) return;
      shell.setAttribute('hidden', 'hidden');
      document.body.classList.remove('modal-open');
    };

    const openModal = (shell) => {
      if (!shell) return;
      modalShells.forEach((s) => s.setAttribute('hidden', 'hidden'));
      shell.removeAttribute('hidden');
      document.body.classList.add('modal-open');
    };

    modalTriggers.forEach((trigger) => {
      trigger.addEventListener('click', () => {
        openModal(document.getElementById(trigger.getAttribute('data-modal-open') || ''));
      });
    });

    modalClosers.forEach((closer) => {
      closer.addEventListener('click', () => closeModal(closer.closest('[data-modal-shell]')));
    });

    modalShells.forEach((shell) => {
      shell.addEventListener('click', (e) => { if (e.target === shell) closeModal(shell); });
    });

    document.addEventListener('keydown', (e) => {
      if (e.key !== 'Escape') return;
      modalShells.forEach((shell) => { if (!shell.hasAttribute('hidden')) closeModal(shell); });
    });

    plannerForms.forEach((form) => {
      form.addEventListener('submit', () => {
        const lbl = form.getAttribute('data-busy-title') || 'Procesando acción';
        const msg = form.getAttribute('data-busy-message') || 'La operación está en curso. Esta página se actualizará cuando termine.';
        if (busyTitle)   busyTitle.textContent   = lbl;
        if (busyMessage) busyMessage.textContent  = msg;
        if (busyOverlay) busyOverlay.removeAttribute('hidden');
        document.body.classList.remove('modal-open');
        const btn = form.querySelector('button[type="submit"]');
        if (btn) btn.disabled = true;
      });
    });
  })();

  /* ── Chat drawer ─────────────────────────────────── */
  (function chat() {
    const toggle       = document.querySelector('[data-chat-toggle]');
    const shell        = document.querySelector('[data-chat-shell]');
    const closeItems   = document.querySelectorAll('[data-chat-close]');
    const messagesEl   = document.querySelector('[data-chat-messages]');
    const emptyEl      = document.querySelector('[data-chat-empty]');
    const inputEl      = document.querySelector('[data-chat-input]');
    const sendButton   = document.querySelector('[data-chat-send]');
    const newButton    = document.querySelector('[data-chat-new]');
    const confirmBox   = document.querySelector('[data-chat-confirm]');
    const confirmReason  = document.querySelector('[data-chat-confirm-reason]');
    const confirmButton  = document.querySelector('[data-chat-confirm-button]');
    const convList     = document.querySelector('[data-chat-conv-list]');
    const convTitle    = document.querySelector('[data-chat-conv-title]');
    const modelBadge   = document.querySelector('[data-chat-model-badge]');
    const thinkingEl   = document.querySelector('[data-chat-thinking]');
    if (!toggle || !shell || !messagesEl || !inputEl || !sendButton) return;

    let busy = false;

    const escapeHtml = (s) =>
      String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

    const formatText = (text) => escapeHtml(text).replace(/\n/g, '<br>');

    const renderMessages = (items) => {
      messagesEl.querySelectorAll('.chat-bubble-wrap').forEach((el) => el.remove());
      if (emptyEl) emptyEl.hidden = Array.isArray(items) && items.length > 0;
      if (!Array.isArray(items) || !items.length) return;
      items.forEach((item) => {
        const wrap   = document.createElement('div');
        wrap.className = 'chat-bubble-wrap ' + (item.role === 'assistant' ? 'is-assistant' : 'is-user') + (item.error ? ' is-error' : '');
        const bubble = document.createElement('div');
        bubble.className = 'chat-bubble';
        bubble.innerHTML = formatText(item.text || '');
        const meta = document.createElement('div');
        meta.className = 'chat-bubble-meta';
        const timeStr = item.created_at ? new Date(item.created_at).toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' }) : '';
        meta.textContent = [item.role === 'assistant' ? 'Entrenador' : 'Tú', item.model, timeStr].filter(Boolean).join(' · ');
        wrap.appendChild(bubble);
        wrap.appendChild(meta);
        messagesEl.appendChild(wrap);
      });
      messagesEl.scrollTop = messagesEl.scrollHeight;
    };

    const renderConversations = (conversations, activeId) => {
      if (!convList) return;
      convList.innerHTML = '';
      (conversations || []).forEach((conv) => {
        const item  = document.createElement('button');
        item.className = 'chat-conv-item' + (conv.id === activeId ? ' is-active' : '');
        item.type = 'button';
        item.dataset.convId = conv.id;
        const title = document.createElement('span');
        title.className = 'chat-conv-item-title';
        title.textContent = conv.title || 'Conversación';
        const del = document.createElement('button');
        del.className = 'chat-conv-delete';
        del.type = 'button';
        del.title = 'Eliminar';
        del.dataset.deleteConvId = conv.id;
        del.innerHTML = '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';
        item.appendChild(title);
        item.appendChild(del);
        convList.appendChild(item);
      });
    };

    const renderConfirm = (pending) => {
      if (!confirmBox) return;
      if (!pending || !pending.id) {
        confirmBox.hidden = true;
        if (confirmButton) confirmButton.dataset.confirmationId = '';
        return;
      }
      confirmBox.hidden = false;
      if (confirmReason) confirmReason.textContent = pending.reason || 'Confirmación requerida.';
      if (confirmButton) confirmButton.dataset.confirmationId = pending.id;
    };

    const renderState = (state) => {
      renderMessages(state.history || []);
      renderConversations(state.conversations || [], state.active_conversation_id);
      renderConfirm(state.pending_confirmation || null);
      if (convTitle) {
        const active = (state.conversations || []).find((c) => c.id === state.active_conversation_id);
        convTitle.textContent = active ? active.title : 'Conversación';
      }
      if (modelBadge) modelBadge.textContent = state.active_model || '';
    };

    const setThinking = (value) => {
      busy = value;
      if (sendButton)   sendButton.disabled   = value;
      if (confirmButton) confirmButton.disabled = value;
      if (thinkingEl)   thinkingEl.hidden     = !value;
      if (inputEl)      inputEl.disabled      = value;
    };

    const apiPost = async (u, body) => {
      const r = await fetch(u, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {}),
      });
      const d = await r.json();
      if (!r.ok || !d.ok) throw new Error(d.error || d.message || 'Error.');
      return d;
    };

    const apiDelete = async (u) => {
      const r = await fetch(u, { method: 'DELETE', credentials: 'same-origin' });
      const d = await r.json();
      if (!r.ok || !d.ok) throw new Error(d.error || 'Error.');
      return d;
    };

    const loadState = async () => {
      const r = await fetch(url('chatStateUrl'), { credentials: 'same-origin' });
      const p = await r.json();
      if (!r.ok || !p.ok) throw new Error(p.error || 'No pude cargar el chat.');
      renderState(p.state || {});
    };

    const addOptimisticMessage = (text) => {
      if (emptyEl) emptyEl.hidden = true;
      const wrap   = document.createElement('div');
      wrap.className = 'chat-bubble-wrap is-user';
      const bubble = document.createElement('div');
      bubble.className = 'chat-bubble';
      bubble.innerHTML = formatText(text);
      wrap.appendChild(bubble);
      messagesEl.appendChild(wrap);
      messagesEl.scrollTop = messagesEl.scrollHeight;
    };

    toggle.addEventListener('click', async () => {
      shell.hidden = false;
      document.body.classList.add('chat-open');
      // Reset any stuck state from a previous timed-out request
      setThinking(false);
      renderConfirm(null);
      try { await loadState(); }
      catch (e) { if (convTitle) convTitle.textContent = e.message || 'Error cargando chat.'; }
    });

    closeItems.forEach((el) => el.addEventListener('click', () => {
      shell.hidden = true;
      document.body.classList.remove('chat-open');
    }));

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !shell.hidden) {
        shell.hidden = true;
        document.body.classList.remove('chat-open');
      }
    });

    const sendMessage = async () => {
      if (busy) return;
      const message = (inputEl.value || '').trim();
      if (!message) return;
      inputEl.value = '';
      inputEl.style.height = '';
      addOptimisticMessage(message);
      setThinking(true);
      const abort = new AbortController();
      const abortTimer = setTimeout(() => abort.abort(), 100000); // 100s hard client timeout
      try {
        const r = await fetch(url('chatMessageUrl'), {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ message }),
          signal: abort.signal,
        });
        clearTimeout(abortTimer);
        const d = await r.json();
        if (!r.ok || !d.ok) throw new Error(d.error || d.message || 'Error.');
        renderState(d.state || {});
      } catch (e) {
        clearTimeout(abortTimer);
        const errWrap   = document.createElement('div');
        errWrap.className = 'chat-bubble-wrap is-assistant is-error';
        const errBubble = document.createElement('div');
        errBubble.className = 'chat-bubble';
        errBubble.textContent = e.name === 'AbortError'
          ? 'Sin respuesta en 100s. El entrenador puede seguir procesando — vuelve a abrir el chat para ver si respondió.'
          : (e.message || 'Error enviando mensaje.');
        errWrap.appendChild(errBubble);
        messagesEl.appendChild(errWrap);
        messagesEl.scrollTop = messagesEl.scrollHeight;
      } finally {
        setThinking(false);
        inputEl.focus();
      }
    };

    sendButton.addEventListener('click', sendMessage);

    inputEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });

    inputEl.addEventListener('input', () => {
      inputEl.style.height = 'auto';
      inputEl.style.height = Math.min(inputEl.scrollHeight, 160) + 'px';
    });

    if (newButton) {
      newButton.addEventListener('click', async () => {
        try {
          const d = await apiPost(url('chatConversationsUrl'), {});
          renderState(d.state || {});
        } catch (e) { if (convTitle) convTitle.textContent = e.message || 'Error.'; }
      });
    }

    if (convList) {
      convList.addEventListener('click', async (e) => {
        const delBtn = e.target.closest('[data-delete-conv-id]');
        if (delBtn) {
          e.stopPropagation();
          try {
            const d = await apiDelete(url('chatConversationsUrl') + '/' + delBtn.dataset.deleteConvId);
            renderState(d.state || {});
          } catch (_) {}
          return;
        }
        const item = e.target.closest('[data-conv-id]');
        if (item) {
          try {
            const d = await apiPost(url('chatSwitchUrl'), { conversation_id: item.dataset.convId });
            renderState(d.state || {});
          } catch (_) {}
        }
      });
    }

    if (confirmButton) {
      confirmButton.addEventListener('click', async () => {
        const id = confirmButton.dataset.confirmationId || '';
        if (!id || busy) return;
        setThinking(true);
        try {
          const d = await apiPost(url('chatConfirmUrl'), { confirmation_id: id });
          renderState(d.state || {});
        } catch (_) {} finally { setThinking(false); }
      });
    }
  })();

})();
