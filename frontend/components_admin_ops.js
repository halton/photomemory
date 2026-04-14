// 操作逻辑模块，包括 approve/reject/revoke，解耦视图

/**
 * 发送批准请求
 * @param {string} deviceId
 * @param {string} token
 * @param {Function} showToast - 提示
 * @param {Function} loadList - 刷新数据
 */
export async function approve(deviceId, token, showToast, loadList) {
  const r = await fetch(`${window.API}/pair/approve`, {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ device_id: deviceId }),
  });
  if (r.ok) { showToast('✅ 已批准'); loadList(); }
  else showToast('操作失败: ' + r.status, true);
}

/**
 * 发送拒绝请求
 */
export async function reject(deviceId, token, showToast, loadList) {
  const r = await fetch(`${window.API}/pair/reject`, {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ device_id: deviceId }),
  });
  if (r.ok) { showToast('🗑️ 已拒绝'); loadList(); }
  else showToast('操作失败: ' + r.status, true);
}

/**
 * 发送吊销请求
 */
export async function revoke(deviceId, name, token, showToast, loadList) {
  if (!confirm(`确认吊销设备「${name}」？`)) return;
  const r = await fetch(`${window.API}/pair/revoke`, {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ device_id: deviceId }),
  });
  if (r.ok) { showToast('🔒 已吊销'); loadList(); }
  else showToast('操作失败: ' + r.status, true);
}
