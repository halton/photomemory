// 渲染函数模块：待审批与已配对设备表格
// 仅负责渲染 view，与操作解耦，便于管理

/**
 * 渲染所有数据，包含 pending 与 paired
 * @param {Object} data - 含 pending, paired 两数组
 * @param {Object} renderers - 渲染用依赖，如 showToast/esc/shortId/fmt
 */
export function renderAll(data, renderers) {
  renderPending(data.pending || [], renderers);
  renderPaired(data.paired || [], renderers);
}

/**
 * 渲染待审批设备
 * @param {Array} list - 设备数组
 * @param {Object} renderers - 依赖
 */
export function renderPending(list, { showToast, esc, fmt, approve, reject }) {
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
        <button class="btn approve sm" onclick="window.approve('${esc(d.device_id)}')">批准</button>
        <button class="btn danger sm" onclick="window.reject('${esc(d.device_id)}')">拒绝</button>
      </td>
    </tr>
  `).join('');
}

/**
 * 渲染已配对设备
 * @param {Array} list
 * @param {Object} renderers
 */
export function renderPaired(list, { esc, shortId, fmt, revoke }) {
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
      <td><span class="${d.status === 'active' ? 'status-active' : 'status-revoked'}">${d.status === 'active' ? '✔ 活跃' : '✗ 已吊销'}</span></td>
      <td>
        ${d.status === 'active'
          ? `<button class="btn danger sm" onclick="window.revoke('${esc(d.device_id)}', '${esc(d.device_name)}')">吊销</button>`
          : '<span style="color:#444;font-size:12px">已吊销</span>'}
      </td>
    </tr>
  `).join('');
}
