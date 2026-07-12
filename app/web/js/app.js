const { createApp } = Vue;

// SHA256 降级实现，HTTP 环境下 crypto.subtle 不可用时使用
function SHA256_fallback(msg) {
  function rotr(x, n) { return (x >>> n) | (x << (32 - n)); }
  function ch(x, y, z) { return (x & y) ^ (~x & z); }
  function maj(x, y, z) { return (x & y) ^ (x & z) ^ (y & z); }
  function bsig0(x) { return rotr(x, 2) ^ rotr(x, 13) ^ rotr(x, 22); }
  function bsig1(x) { return rotr(x, 6) ^ rotr(x, 11) ^ rotr(x, 25); }
  function ssig0(x) { return rotr(x, 7) ^ rotr(x, 18) ^ (x >>> 3); }
  function ssig1(x) { return rotr(x, 17) ^ rotr(x, 19) ^ (x >>> 10); }

  const K = [0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
    0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
    0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
    0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
    0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
    0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2];

  const bytes = new TextEncoder().encode(msg);
  const bitLen = bytes.length * 8;
  const padLen = ((bytes.length + 9 + 63) >>> 6) << 6;
  const padded = new Uint8Array(padLen);
  padded.set(bytes);
  padded[bytes.length] = 0x80;
  const dv = new DataView(padded.buffer);
  dv.setUint32(padLen - 4, bitLen, false);

  const H = [0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];

  for (let i = 0; i < padLen; i += 64) {
    const W = new Uint32Array(64);
    for (let t = 0; t < 16; t++) W[t] = dv.getUint32(i + t * 4, false);
    for (let t = 16; t < 64; t++) W[t] = (ssig1(W[t-2]) + W[t-7] + ssig0(W[t-15]) + W[t-16]) >>> 0;
    let [a, b, c, d, e, f, g, h] = H;
    for (let t = 0; t < 64; t++) {
      const T1 = (h + bsig1(e) + ch(e,f,g) + K[t] + W[t]) >>> 0;
      const T2 = (bsig0(a) + maj(a,b,c)) >>> 0;
      h = g; g = f; f = e; e = (d + T1) >>> 0; d = c; c = b; b = a; a = (T1 + T2) >>> 0;
    }
    H[0] = (H[0] + a) >>> 0; H[1] = (H[1] + b) >>> 0; H[2] = (H[2] + c) >>> 0; H[3] = (H[3] + d) >>> 0;
    H[4] = (H[4] + e) >>> 0; H[5] = (H[5] + f) >>> 0; H[6] = (H[6] + g) >>> 0; H[7] = (H[7] + h) >>> 0;
  }
  return H.map(v => v.toString(16).padStart(8, "0")).join("");
}

const WELCOME = [
  "你好，我是 **SecKB 企业网络安全助手**。",
  "",
  "可以聊聊漏洞分析与利用、加固建议、等保合规、应急响应这些方向，有问题直接问。",
].join("\n");

createApp({
  data() {
    return {
      view: "chat",
      dark: true,
      showLogin: false,
      threadId: this.newThreadId(),
      draft: "",
      isStreaming: false,
      stopRequested: false,
      streamReader: null,
      abortController: null,
      messages: [{ role: "bot", content: WELCOME }],
      // 文档
      docs: [], docSearch: "", docSearchInput: "", pageSize: 10, page: 1,
      total: 0, totalPages: 0, dragging: false, uploading: false, uploadingFiles: [],
      // 认证
      currentUser: null,
      authReady: false,
      loginForm: { username: "", password: "", error: "", loading: false },
      // 用户管理
      userList: [], showUserForm: false, editingUser: null,
      userForm: { username: "", password: "", role: "user" },
      userFormError: "", userSaving: false,
      // 审计
      auditLogs: [], auditPage: 1, auditTotal: 0, auditTotalPages: 0,
      selectedLogIds: [],
      // 对话列表
      conversations: [],
      editingConvId: null,
      editingConvTitle: "",
      // 知识图谱
      graphQuery: "",
      graphNetwork: null,
      graphLoading: false,
      graphError: "",
      LABEL_COLORS: {
        "漏洞": "#f87171", "攻击手法": "#fb923c", "安全工具": "#a78bfa",
        "网络协议": "#60a5fa", "防御措施": "#34d399", "合规标准": "#fbbf24",
        "威胁组织": "#f472b6",
      },
    };
  },
  async mounted() {
    document.documentElement.classList.toggle("dark", this.dark);
    try {
      const r = await this.apiFetch("/auth/me");
      if (r.ok) this.currentUser = await r.json();
    } catch (e) { /* Cookie 无效或未登录 */ }
    this.authReady = true;
    if (this.currentUser) {
      this.loadConversations();
      this._tokenRefreshTimer = setInterval(async () => {
        try { await this.apiFetch("/auth/me"); } catch (e) {}
      }, 15 * 60 * 1000);
    }
    this.loadChatSession();
  },
  beforeUnmount() {
    if (this._tokenRefreshTimer) { clearInterval(this._tokenRefreshTimer); this._tokenRefreshTimer = null; }
  },
  computed: {
    isAdmin() { return this.currentUser && this.currentUser.role === "admin"; },
    isAuditor() { return this.currentUser && this.currentUser.role === "auditor"; },
    rangeStart() { return this.total === 0 ? 0 : (this.page - 1) * this.pageSize + 1; },
    rangeEnd() { return Math.min(this.page * this.pageSize, this.total); },
    storageKey() {
      if (this.currentUser) return "rag_ls_" + this.currentUser.id + "_" + this.threadId;
      return "rag_ss_" + this.threadId;
    },
  },
  methods: {
    newThreadId() { return "web-" + Date.now() + "-" + Math.random().toString(36).slice(2, 8); },
    renderMd(text) { if (!text) return ""; const raw = marked.parse(text, { breaks: true, gfm: true }); return DOMPurify.sanitize(raw, { ALLOWED_TAGS: ['h1','h2','h3','h4','h5','h6','p','br','strong','em','u','s','del','ins','a','ul','ol','li','blockquote','pre','code','table','thead','tbody','tr','th','td','hr','img'], ALLOWED_ATTR: ['href','src','alt','title','class'] }); },
    toggleTheme() { this.dark = !this.dark; document.documentElement.classList.toggle("dark", this.dark); },

    async apiFetch(url, options = {}) {
      return await fetch(url, Object.assign({}, options, { credentials: "same-origin" }));
    },

    async apiFetchAuth(url, options = {}) {
      const r = await this.apiFetch(url, options);
      if (r.status === 401) {
        this.doLogout();
        throw new Error("未授权，请重新登录");
      }
      return r;
    },

    // ===== 登录 / 登出 =====
    async sha256(text) {
      if (crypto.subtle && crypto.subtle.digest) {
        const buf = new TextEncoder().encode(text);
        const hash = await crypto.subtle.digest("SHA-256", buf);
        return Array.from(new Uint8Array(hash)).map(b => b.toString(16).padStart(2, "0")).join("");
      }
      return SHA256_fallback(text);
    },
    async computePoW(challenge, difficulty) {
      let nonce = 0;
      const prefix = "0".repeat(difficulty);
      while (true) {
        const h = await this.sha256(challenge + ":" + nonce);
        if (h.startsWith(prefix)) return String(nonce);
        nonce++;
      }
    },
    async doLogin() {
      this.loginForm.error = "";
      const u = this.loginForm.username.trim();
      const p = this.loginForm.password;
      if (!u || !p) { this.loginForm.error = "用户名和密码不能为空"; return; }
      this.loginForm.loading = true;
      try {
        this.loginForm.error = "正在验证安全令牌…";
        const sr = await fetch("/auth/login-salt");
        if (!sr.ok) { this.loginForm.error = "获取安全令牌失败，请刷新重试"; this.loginForm.loading = false; return; }
        const sd = await sr.json();
        this.loginForm.error = "正在进行安全校验…";
        const pow_nonce = await this.computePoW(sd.challenge, sd.difficulty);
        const sign = await this.sha256(u + ":" + p + ":" + sd.salt);
        this.loginForm.error = "";
        const r = await fetch("/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username: u, password: p, salt: sd.salt, sign: sign, pow_nonce: pow_nonce }),
        });
        const data = await r.json();
        if (!r.ok) { this.loginForm.error = data.detail || "登录失败"; return; }
        this.currentUser = data.user;
        this.loginForm.password = "";
        this.showLogin = false;
        this.loadConversations().then(() => {
          if (this.conversations.length > 0) {
            this.threadId = this.conversations[0].thread_id;
          } else {
            this.threadId = this.newThreadId();
          }
          this.loadChatSession();
        });
      } catch (e) {
        this.loginForm.error = "网络错误：" + e.message;
      } finally {
        this.loginForm.loading = false;
      }
    },
    doLogout() {
      fetch("/auth/logout", { method: "POST", credentials: "same-origin" });
      this.currentUser = null;
      this.loadChatSession();
    },

    // ===== 会话存储 =====
    loadChatSession() {
      if (this.currentUser) {
        this.loadChatSessionFromBackend();
      } else {
        const saved = sessionStorage.getItem(this.storageKey);
        if (saved) {
          try { this.messages = JSON.parse(saved); } catch (e) { this.messages = [{ role: "bot", content: WELCOME }]; }
        } else {
          this.messages = [{ role: "bot", content: WELCOME }];
        }
      }
    },
    async loadChatSessionFromBackend() {
      let msgs = [{ role: "bot", content: WELCOME }];
      try {
        const r = await this.apiFetchAuth("/conversations/" + this.threadId + "/messages");
        if (r.ok) {
          const d = await r.json();
          const raw = d.messages || [];
          if (raw.length > 0) {
            const result = [];
            for (let i = 0; i < raw.length; i += 2) {
              const u = raw[i], b = raw[i + 1];
              if (u && u.role === "user") result.push({ role: "user", content: u.content });
              if (b && b.role === "assistant") result.push({
                role: "bot", content: b.content,
                sources: b.sources || [],
                graphSources: b.graph_sources || [],
              });
            }
            if (result.length > 0) msgs = result;
          }
        }
      } catch (e) { /* 出错保持欢迎消息 */ }
      this.messages = msgs;
      this.$nextTick(() => this.scrollToBottom());
    },
    saveSession() {
      if (this.isStreaming || this.currentUser) return;
      sessionStorage.setItem(this.storageKey, JSON.stringify(this.messages));
    },
    clearHistory() {
      if (this.currentUser) {
        this.deleteConversation(this.threadId);
      } else {
        sessionStorage.removeItem(this.storageKey);
        this.threadId = this.newThreadId();
        this.messages = [{ role: "bot", content: WELCOME }];
      }
    },

    // ===== 对话列表管理 =====
    async loadConversations() {
      if (!this.currentUser) return;
      try {
        const r = await this.apiFetchAuth("/conversations");
        if (!r.ok) return;
        const d = await r.json();
        this.conversations = d.conversations || [];
      } catch (e) { console.error("加载对话列表失败:", e); }
    },
    selectConversation(tid) {
      if (this.isStreaming || tid === this.threadId) return;
      this.saveSession();
      this.threadId = tid;
      this.loadChatSession();
    },
    newConversation() {
      if (this.isStreaming) return;
      if (this.currentUser && this.conversations.length >= 5) {
        alert("最多创建 5 个对话，请先删除旧对话");
        return;
      }
      this.saveSession();
      this.threadId = this.newThreadId();
      this.messages = [{ role: "bot", content: WELCOME }];
      if (this.currentUser) {
        this.conversations.unshift({
          thread_id: this.threadId, title: "新会话",
          created_at: new Date().toISOString(), msg_count: 0,
        });
      }
    },
    async deleteConversation(tid) {
      if (!confirm("确定删除此对话吗？")) return;
      try {
        const r = await this.apiFetchAuth("/conversations/" + tid, { method: "DELETE" });
        if (!r.ok) { const d = await r.json(); alert(d.detail || "删除失败"); return; }
        this.conversations = this.conversations.filter(c => c.thread_id !== tid);
        if (this.threadId === tid) {
          if (this.conversations.length > 0) {
            this.selectConversation(this.conversations[0].thread_id);
          } else {
            this.newConversation();
          }
        }
      } catch (e) { alert("删除失败：" + e.message); }
    },
    startRename(tid, title) {
      this.editingConvId = tid;
      this.editingConvTitle = title;
      this.$nextTick(() => {
        const el = this.$el.querySelector(".conv-edit-input");
        if (el) { el.focus(); el.select(); }
      });
    },
    cancelRename() {
      this.editingConvId = null;
      this.editingConvTitle = "";
    },
    async saveRename(tid) {
      const title = this.editingConvTitle.trim();
      if (!title) { this.cancelRename(); return; }
      try {
        const r = await this.apiFetchAuth("/conversations/" + tid, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ title }),
        });
        if (!r.ok) { const d = await r.json(); alert(d.detail || "重命名失败"); return; }
        const c = this.conversations.find(c => c.thread_id === tid);
        if (c) c.title = title;
        this.cancelRename();
      } catch (e) { alert("重命名失败：" + e.message); }
    },

    // ===== 对话 =====
    scrollToBottom() {
      this.$nextTick(() => { const el = this.$refs.messages; if (el) el.scrollTo({ top: el.scrollHeight, behavior: "instant" }); });
    },
    autoGrow(e) { const t = e.target; t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 140) + "px"; },
    onKeydown(e) { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); this.send(); } },

    async send() {
      const text = this.draft.trim();
      if (!text || this.isStreaming) return;
      this.stopRequested = false;
      this.messages.push({ role: "user", content: text });
      this.draft = "";
      if (this.$refs.input) this.$refs.input.style.height = "auto";
      this.messages.push({ role: "bot", content: "", streaming: true, sources: [], graphSources: [] });
      const bot = this.messages[this.messages.length - 1];
      this.scrollToBottom();
      this.isStreaming = true;
      this.abortController = new AbortController();
      this.streamReader = null;
      let finished = false;
      try {
        const resp = await fetch("/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: text, thread_id: this.threadId }),
          signal: this.abortController.signal,
          credentials: "same-origin",
        });
        if (!resp.ok) throw new Error("HTTP " + resp.status);
        if (!resp.body) throw new Error("响应体为空");
        const reader = resp.body.getReader();
        this.streamReader = reader;
        const decoder = new TextDecoder("utf-8");
        let buffer = "";
        while (!finished) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const parts = buffer.split("\n\n");
          buffer = parts.pop() || "";
          for (const part of parts) {
            const line = part.trim();
            if (!line.startsWith("data:")) continue;
            const payload = line.slice(5).trim();
            if (!payload) continue;
            if (payload === "[DONE]") { finished = true; break; }
            let data;
            try { data = JSON.parse(payload); } catch (e) { continue; }
            if (data.error) { bot.content += "\n[出错] " + data.error; }
            else if (data.sources || data.graph_sources) {
              if (data.sources) bot.sources = data.sources;
              if (data.graph_sources) bot.graphSources = data.graph_sources;
              this.scrollToBottom();
            }
            else if (data.content) { bot.content += data.content; this.scrollToBottom(); }
          }
        }
        if (!bot.content && !this.stopRequested) bot.content = "（未返回内容）";
      } catch (err) {
        if (!this.stopRequested && err.name !== "AbortError") bot.content = "请求失败：" + err.message;
      } finally {
        bot.streaming = false;
        this.isStreaming = false;
        this.abortController = null;
        this.streamReader = null;
        if (this.stopRequested && !bot.content) this.messages = this.messages.filter((m) => m !== bot);
        this.stopRequested = false;
        this.saveSession();
        if (this.currentUser) {
          const conv = this.conversations.find(c => c.thread_id === this.threadId);
          if (conv) {
            conv.msg_count = this.messages.filter(m => m.role !== "bot" || (m.role === "bot" && !m._welcome)).length;
            if (conv.title === "新会话") {
              const first = this.messages.find(m => m.role === "user");
              if (first) conv.title = first.content.slice(0, 50);
            }
          } else {
            this.loadConversations();
          }
        }
        this.$nextTick(() => this.$refs.input && this.$refs.input.focus());
      }
    },
    stopStreaming() {
      if (!this.isStreaming) return;
      this.stopRequested = true;
      if (this.streamReader) { this.streamReader.cancel().catch(() => {}); this.streamReader = null; }
      if (this.abortController) this.abortController.abort();
      this.isStreaming = false;
    },

    // ===== 文档管理 =====
    mapDoc(d) { return { id: d.id, name: d.original_filename, size: d.file_size != null ? this.formatSize(d.file_size) : "-", time: d.created_at || "-" }; },
    async loadDocuments() {
      try {
        const params = new URLSearchParams({ page: String(this.page), page_size: String(this.pageSize) });
        if (this.docSearch) params.set("keyword", this.docSearch);
        const r = await this.apiFetch("/documents?" + params.toString());
        if (!r.ok) throw new Error("HTTP " + r.status);
        const data = await r.json();
        this.docs = (data.documents || []).map((d) => this.mapDoc(d));
        this.total = data.total || 0; this.totalPages = data.total_pages || 0;
      } catch (err) { console.error("加载文档列表失败:", err); }
    },
    onDocSearchInput(e) {
      this.docSearchInput = e.target.value;
      clearTimeout(this._searchTimer);
      this._searchTimer = setTimeout(() => { this.docSearch = this.docSearchInput.trim(); this.page = 1; this.loadDocuments(); }, 300);
    },
    goToPage(p) { if (p < 1 || p > this.totalPages || p === this.page) return; this.page = p; this.loadDocuments(); },
    prevPage() { this.goToPage(this.page - 1); },
    nextPage() { this.goToPage(this.page + 1); },
    onPageSizeChange() { this.page = 1; this.loadDocuments(); },
    triggerUpload() { if (this.uploading) return; this.$refs.file && this.$refs.file.click(); },
    onPick(e) { this.addFiles(Array.from(e.target.files || [])); e.target.value = ""; },
    onDrop(e) { this.dragging = false; this.addFiles(Array.from(e.dataTransfer.files || [])); },
    async addFiles(files) {
      const valid = files.filter((f) => /\.(txt|pdf|csv|md)$/i.test(f.name));
      if (files.length - valid.length > 0) alert("已忽略 " + (files.length - valid.length) + " 个不支持的文件");
      if (!valid.length) return;
      this.uploading = true;
      try {
        for (const f of valid) {
          this.uploadingFiles.push({ name: f.name, size: this.formatSize(f.size), percent: 0, phase: "uploading" });
          const entry = this.uploadingFiles[this.uploadingFiles.length - 1];
          try { await this.uploadOne(f, entry); } catch (err) { alert("「" + f.name + "」上传失败：" + err.message); }
          finally { this.uploadingFiles = this.uploadingFiles.filter((e) => e !== entry); }
        }
        await this.loadDocuments();
      } finally { this.uploading = false; }
    },
    uploadOne(file, entry) {
      return new Promise((resolve, reject) => {
        const form = new FormData(); form.append("files", file);
        const xhr = new XMLHttpRequest();
        xhr.open("POST", "/documents/upload");
        xhr.withCredentials = true;
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) { entry.percent = Math.round((e.loaded / e.total) * 100); if (entry.percent >= 100) entry.phase = "vectorizing"; }
        };
        xhr.upload.onload = () => { entry.percent = 100; entry.phase = "vectorizing"; };
        xhr.onload = () => {
          if (xhr.status === 401) { this.doLogout(); reject(new Error("未授权")); return; }
          if (xhr.status >= 200 && xhr.status < 300) { let d = null; try { d = JSON.parse(xhr.responseText); } catch (e) {} resolve(d); }
          else { let m = "HTTP " + xhr.status; try { m = JSON.parse(xhr.responseText).detail || m; } catch (e) {} reject(new Error(m)); }
        };
        xhr.onerror = () => reject(new Error("网络错误"));
        xhr.send(form);
      });
    },
    async removeDoc(id) {
      const doc = this.docs.find((d) => d.id === id);
      if (!doc || !confirm("确定删除文档「" + doc.name + "」吗？")) return;
      try {
        const r = await this.apiFetchAuth("/documents/" + encodeURIComponent(doc.id), { method: "DELETE" });
        if (!r.ok) { let m = "HTTP " + r.status; try { m = (await r.json()).detail || m; } catch (e) {} throw new Error(m); }
        if (this.docs.length <= 1 && this.page > 1) this.page -= 1;
        await this.loadDocuments();
      } catch (err) { alert("删除失败：" + err.message); }
    },
    async previewDoc(id) {
      const doc = this.docs.find((d) => d.id === id);
      if (!doc) return;
      const ext = (doc.name || "").split(".").pop().toLowerCase();
      if (ext === "pdf") {
        window.open("/documents/" + id + "/preview", "_blank");
        return;
      }
      try {
        const r = await this.apiFetchAuth("/documents/" + id + "/preview");
        if (!r.ok) { alert("预览失败"); return; }
        const data = await r.json();
        const w = window.open("", "_blank", "width=800,height=600");
        if (!w) { alert("请允许弹出窗口以预览文档"); return; }
        w.document.title = data.filename;
        w.document.body.innerHTML = "<pre style='white-space:pre-wrap;font-family:monospace;padding:20px;max-width:100%;overflow-x:auto;'>" + this.escapeHtml(data.content) + "</pre>";
      } catch (e) { alert("预览失败：" + e.message); }
    },
    downloadDoc(id) {
      window.open("/documents/" + id + "/download", "_blank");
    },
    escapeHtml(text) {
      const d = document.createElement("div");
      d.textContent = text;
      return d.innerHTML;
    },
    async copyMessage(idx) {
      const m = this.messages[idx];
      if (!m || !m.content) return;
      try {
        await navigator.clipboard.writeText(m.content);
        this.$set(m, "_copied", true);
        setTimeout(() => { if (m._copied) { this.$set(m, "_copied", false); } }, 1500);
      } catch (e) {
        const ta = document.createElement("textarea");
        ta.value = m.content;
        ta.style.position = "fixed"; ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
        this.$set(m, "_copied", true);
        setTimeout(() => { if (m._copied) { this.$set(m, "_copied", false); } }, 1500);
      }
    },
    formatSize(bytes) {
      if (bytes < 1024) return bytes + " B";
      if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
      return (bytes / 1024 / 1024).toFixed(1) + " MB";
    },

    // ===== 用户管理 =====
    roleLabel(r) { const m = { admin: "管理员", user: "游客", auditor: "审计员" }; return m[r] || r; },
    roleTag(r) { const m = { admin: "admin-tag", user: "user-tag", auditor: "audit-tag" }; return m[r] || ""; },
    resetUserForm() { this.editingUser = null; this.userForm = { username: "", password: "", role: "user" }; this.userFormError = ""; },
    editUser(u) { this.editingUser = u; this.userForm = { username: u.username, password: "", role: u.role }; this.userFormError = ""; this.showUserForm = true; },
    async loadUsers() {
      try { const r = await this.apiFetchAuth("/users?page_size=100"); if (!r.ok) throw new Error("HTTP " + r.status); const d = await r.json(); this.userList = d.users || []; }
      catch (err) { console.error("加载用户列表失败:", err); }
    },
    async saveUser() {
      this.userFormError = "";
      const { username, password, role } = this.userForm;
      if (!username) { this.userFormError = "用户名不能为空"; return; }
      if (!this.editingUser && !password) { this.userFormError = "密码不能为空"; return; }
      this.userSaving = true;
      try {
        const body = { username, password, role };
        let r;
        if (this.editingUser) {
          if (!password) delete body.password;
          r = await this.apiFetchAuth("/users/" + this.editingUser.id, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
        } else {
          r = await this.apiFetchAuth("/users", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
        }
        if (!r.ok) { const d = await r.json(); this.userFormError = d.detail || "操作失败"; return; }
        this.showUserForm = false; this.loadUsers();
      } catch (err) { this.userFormError = "网络错误：" + err.message; }
      finally { this.userSaving = false; }
    },
    async deleteUser(u) {
      if (!confirm("确定删除用户「" + u.username + "」吗？")) return;
      try {
        const r = await this.apiFetchAuth("/users/" + u.id, { method: "DELETE" });
        if (!r.ok) { const d = await r.json(); alert(d.detail || "删除失败"); return; }
        this.loadUsers();
      } catch (err) { alert("删除失败：" + err.message); }
    },

    // ===== 审计 =====
    auditActionLabel(a) {
      const m = { login: "登录", upload: "上传文档", delete: "删除文档", user_create: "创建用户", user_update: "修改用户", user_delete: "删除用户", audit_delete: "删除日志", audit_clear_all: "清空日志" };
      return m[a] || a;
    },
    async loadAuditLogs() {
      try {
        const r = await this.apiFetchAuth("/audit?page=" + this.auditPage + "&page_size=20");
        if (!r.ok) throw new Error("HTTP " + r.status);
        const d = await r.json();
        this.auditLogs = d.logs || []; this.auditTotal = d.total || 0; this.auditTotalPages = d.total_pages || 0;
        this.selectedLogIds = [];
      } catch (err) { console.error("加载审计日志失败:", err); }
    },
    auditGoToPage(p) { if (p < 1 || p > this.auditTotalPages || p === this.auditPage) return; this.auditPage = p; this.loadAuditLogs(); },
    allLogsSelected() {
      return this.auditLogs.length > 0 && this.selectedLogIds.length === this.auditLogs.length;
    },
    toggleSelectAll() {
      if (this.allLogsSelected()) { this.selectedLogIds = []; }
      else { this.selectedLogIds = this.auditLogs.map(l => l.id); }
    },
    toggleLogSelect(id) {
      const idx = this.selectedLogIds.indexOf(id);
      if (idx >= 0) this.selectedLogIds.splice(idx, 1);
      else this.selectedLogIds.push(id);
    },
    async deleteSingleLog(id) {
      if (!confirm("确定删除此条日志吗？")) return;
      try {
        const r = await this.apiFetchAuth("/audit", {
          method: "DELETE",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ids: [id] }),
        });
        if (!r.ok) { const d = await r.json(); alert(d.detail || "删除失败"); return; }
        if (this.auditLogs.length <= 1 && this.auditPage > 1) this.auditPage--;
        this.loadAuditLogs();
      } catch (e) { alert("删除失败：" + e.message); }
    },
    async deleteSelectedLogs() {
      if (!this.selectedLogIds.length) { alert("请先选择要删除的日志"); return; }
      if (!confirm("确定删除选中的 " + this.selectedLogIds.length + " 条日志吗？")) return;
      try {
        const r = await this.apiFetchAuth("/audit", {
          method: "DELETE",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ids: [...this.selectedLogIds] }),
        });
        if (!r.ok) { const d = await r.json(); alert(d.detail || "删除失败"); return; }
        if (this.auditLogs.length <= this.selectedLogIds.length && this.auditPage > 1) this.auditPage--;
        this.loadAuditLogs();
      } catch (e) { alert("删除失败：" + e.message); }
    },
    async clearAllLogs() {
      if (!confirm("确定清空全部审计日志吗？此操作不可恢复。")) return;
      if (!confirm("再次确认：清空后所有日志将被永久删除。")) return;
      try {
        const r = await this.apiFetchAuth("/audit/all", { method: "DELETE" });
        if (!r.ok) { const d = await r.json(); alert(d.detail || "清空失败"); return; }
        this.auditPage = 1;
        this.loadAuditLogs();
      } catch (e) { alert("清空失败：" + e.message); }
    },

    // ===== 知识图谱 =====
    async loadGraphData() {
      this.graphLoading = true;
      this.graphError = "";
      try {
        const r = await this.apiFetchAuth("/graph/search?q=&depth=1");
        if (!r.ok) { this.graphError = "加载失败: HTTP " + r.status; return; }
        const data = await r.json();
        if (!data.entities || !data.entities.length) { this.graphError = "暂无图谱数据，请先上传文档"; return; }
        await this.$nextTick();
        this.renderGraph(data);
      } catch (e) { this.graphError = "加载失败: " + e.message; console.error("加载图谱失败:", e); }
      finally { this.graphLoading = false; }
    },
    async searchGraph() {
      const q = this.graphQuery.trim();
      if (!q) return;
      try {
        const r = await this.apiFetchAuth("/graph/search?q=" + encodeURIComponent(q) + "&depth=1");
        if (!r.ok) return;
        const data = await r.json();
        this.renderGraph(data);
      } catch (e) { console.error("图谱搜索失败:", e); }
    },
    renderGraph(data) {
      const entities = data.entities || [];
      const relations = data.relations || [];
      const container = this.$refs.graphContainer;
      if (!container) { console.error("graphContainer ref 不存在"); return; }
      if (container.clientWidth === 0 || container.clientHeight === 0) { console.error("graphContainer 尺寸为0"); return; }
      if (typeof vis === "undefined") { console.error("vis-network 未加载"); return; }
      if (this.graphNetwork) { this.graphNetwork.destroy(); this.graphNetwork = null; }
      const nodes = new vis.DataSet(entities.map(e => ({
        id: e.id,
        label: e.name,
        color: { background: this.LABEL_COLORS[e.label] || "#94a3b8", border: "#0f172a" },
        font: { color: "#e2e8f0", size: 12 },
        borderWidth: 2,
        shape: "dot",
        size: 18,
      })));
      const edges = new vis.DataSet(relations.map(r => ({
        from: r.source_entity_id,
        to: r.target_entity_id,
        label: r.relation,
        arrows: "to",
        color: { color: "#475569", highlight: "#5eead4" },
        font: { color: "#94a3b8", size: 10, strokeWidth: 0 },
        width: 1,
      })));
      const options = {
        physics: {
          solver: "barnesHut",
          barnesHut: { gravitationalConstant: -2000, centralGravity: 0.3, springLength: 150 },
          stabilization: { iterations: 200, fit: true },
        },
        interaction: { hover: true, tooltipDelay: 200 },
        nodes: { font: { face: "var(--ui)" } },
      };
      this.graphNetwork = new vis.Network(container, { nodes, edges }, options);
      this.graphNetwork.on("doubleClick", async (params) => {
        if (params.nodes.length > 0) {
          try {
            const r = await this.apiFetchAuth("/graph/entities/" + params.nodes[0]);
            if (!r.ok) return;
            const sub = await r.json();
            const existIds = new Set(nodes.getIds());
            (sub.neighbors || []).forEach(n => {
              if (!existIds.has(n.id)) {
                nodes.add({ id: n.id, label: n.name, color: { background: this.LABEL_COLORS[n.label] || "#94a3b8", border: "#0f172a" }, font: { color: "#e2e8f0", size: 12 }, borderWidth: 2, shape: "dot", size: 18 });
                existIds.add(n.id);
              }
            });
            (sub.relations || []).forEach(r => {
              const eid = r.source_entity_id + "_" + r.target_entity_id + "_" + r.relation;
              if (edges.get(eid)) return;
              edges.add({ id: eid, from: r.source_entity_id, to: r.target_entity_id, label: r.relation, arrows: "to", color: { color: "#475569", highlight: "#5eead4" }, font: { color: "#94a3b8", size: 10, strokeWidth: 0 }, width: 1 });
            });
          } catch (e) { console.error("加载邻居节点失败:", e); }
        }
      });
    },
  },
}).mount("#app");
