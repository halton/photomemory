// PhotoMemory 管理后台脚本
// 从 admin.html 拆分

const API = (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
  ? `${location.protocol}//${location.hostname}:8765/api`
  : `${location.protocol}//${location.host}/api`;

let adminToken = localStorage.getItem('pm_admin_token') || '';
let connected = false;
let refreshTimer = null;

if (adminToken) {
  document.getElementById('adminTokenInput').value = adminToken;
  connect();
}

async function connect() {
  const token = document.getElementById('adminTokenInput').value.trim();
  if (!token) return;
  const errEl = document.getElementById('connectError');
  errEl.textContent = '';

  const r = await fetch(`${API}/pair/list`, {
    headers: { 'Authorization': `Bearer ${token}` }
  });
  if (r.ok) {
    adminToken = token;
    localStorage.setItem('pm_admin_token', token);
    connected = true;
    document.getElementById('connBadge').textContent = '已连接';
    document.getElementById('connBadge').className = 'badge connected';
    const data = await r.json();
    renderAll(data);
    startAutoRefresh();
  } else {
    connected = false;
    document.getElementById('connBadge').textContent = '未连接';
    document.getElementById('connBadge').className = 'badge';
    errEl.textContent = r.status === 403 ? 'Token 不正确' : '连接失败: ' + r.status;
  }
}

async function loadList() {
  if (!connected || !adminToken) return;
  const r = await fetch(`${API}/pair/list`, {
    headers: { 'Authorization': `Bearer ${adminToken}` }
  });
  if (r.ok) {
    const data = await r.json();
    renderAll(data);
  }
}

function renderAll(data) {
  renderPending(data.pending || []);
  renderPaired(data.paired || []);
}

function renderPending(list) {
  document.getElementById('pendingCount').textContent = list.length;
  const tbody = document.getElementById('pendingBody');
  if (list.length === 0) {
    tbody.innerHTML = '<tr class="empty-row"><td colspan="5" style="color:#444">暂无待审批设备</td></tr>';
    return;
  }
  tbody.innerHTML = list.map(d => `
    <tr>
      <td><span class="device-name">${esc(d.device_name)}</span></td>
      <td><span class="device-id">${esc(d.device_id)}</span></td>
      <td><span class="date-str">${fmt(d.requested_at)}</span></td>
      <td><span class="ip-str">${esc(d.ip || '-') }</span></td>
      <td style="display:flex;gap:6px">
        <button class="btn approve sm" onclick="approve('${esc(d.device_id)}')">批准</button>
        <button class="btn danger sm" onclick="reject('${esc(d.device_id)}')">拒绝</button>
      </td>
    </tr>
  `).join('');
}

function renderPaired(list) {
  document.getElementById('pairedCount').textContent = list.length;
  const tbody = document.getElementById('pairedBody');
  if (list.length === 0) {
    tbody.innerHTML = '<tr class="empty-row"><td colspan="5" style="color:#444">暂无已配对设备</td></tr>';
    return;
  }
  tbody.innerHTML = list.map(d => `
    <tr>
      <td><span class="device-name">${esc(d.device_name)}</span></td>
      <td><span class="device-id">${shortId(d.device_id)}</span></td>
      <td><span class="date-str">${fmt(d.approved_at)}</span></td>
      <td><span class="${d.status === 'active' ? 'status-active' : 'status-revoked'}">${d.status === 'active' ? '✓ 活跃' : '✗ 已吊销'}</span></td>
      <td>
        ${d.status === 'active'
          ? `<button class="btn danger sm" onclick="revoke('${esc(d.device_id)}', '${esc(d.device_name)}')">吊销</button>`
          : '<span style="color:#444;font-size:12px">已吊销</span>'}
      </td>
    </tr>
  `).join('');
}

async function approve(deviceId) {
  const r = await fetch(`${API}/pair/approve`, {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${adminToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ device_id: deviceId }),
  });
  if (r.ok) { showToast('✅ 已批准'); loadList(); }
  else showToast('操作失败: ' + r.status, true);
}

async function reject(deviceId) {
  const r = await fetch(`${API}/pair/reject`, {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${adminToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ device_id: deviceId }),
  });
  if (r.ok) { showToast('🗑️ 已拒绝'); loadList(); }
  else showToast('操作失败: ' + r.status, true);
}

async function revoke(deviceId, name) {
  if (!confirm(`确认吊销设备「${name}」？`)) return;
  const r = await fetch(`${API}/pair/revoke`, {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${adminToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ device_id: deviceId }),
  });
  if (r.ok) { showToast('🔒 已吊销'); loadList(); }
  else showToast('操作失败: ' + r.status, true);
}

function startAutoRefresh() {
  if (refreshTimer) clearInterval(refreshTimer);
  let countdown = 5;
  const note = document.getElementById('refreshNote');
  const tick = () => {
    note.textContent = `${countdown}s 后刷新`;
    countdown--;
    if (countdown < 0) {
      loadList();
      countdown = 5;
    }
  };
  tick();
  refreshTimer = setInterval(tick, 1000);
}

function showToast(msg, isErr = false) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast show' + (isErr ? ' error' : '');
  setTimeout(() => { t.className = 'toast'; }, 2500);
}

function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function shortId(id) {
  if (!id) return '-';
  return id.length > 20 ? id.slice(0, 10) + '…' + id.slice(-6) : id;
}

function fmt(iso) {
  if (!iso) return '-';
  try {
    return new Date(iso).toLocaleString('zh-CN', {hour12: false});
  } catch { return iso; }
}
