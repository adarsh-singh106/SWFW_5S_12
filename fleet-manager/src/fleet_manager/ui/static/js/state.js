/**
 * Centralized state ownership and lifecycle guarantees.
 * Token is retained strictly in-memory within this module's closure.
 * Persistent storage mechanisms are forbidden.
 */

let _operatorToken = null;
let _selectedNodeId = null;
let _fleetPending = false;
let _selectionEpoch = 0;
let _historySequence = 0;
let _historyOffset = 0;
let _modalReturnFocus = null;
let _inventoryReturnFocus = null;
let _inspectedOperationId = null;
let _currentFilter = "ALL";
let _currentSearch = "";
let _lastFleetData = null;

const _activeRequests = new Set();

export function getOperatorToken() {
  return _operatorToken;
}

export function setOperatorToken(token) {
  _operatorToken = token;
}

export function clearOperatorToken() {
  _operatorToken = null;
}

export function getSelectedNodeId() {
  return _selectedNodeId;
}

export function setSelectedNodeId(id) {
  _selectedNodeId = id;
}

export function getSelectionEpoch() {
  return _selectionEpoch;
}

export function incrementSelectionEpoch() {
  _selectionEpoch++;
  return _selectionEpoch;
}

export function getHistorySequence() {
  return _historySequence;
}

export function incrementHistorySequence() {
  _historySequence++;
  return _historySequence;
}

export function getHistoryOffset() {
  return _historyOffset;
}

export function setHistoryOffset(offset) {
  _historyOffset = Math.max(0, offset);
}

export function isFleetPending() {
  return _fleetPending;
}

export function setFleetPending(pending) {
  _fleetPending = Boolean(pending);
}

export function getCurrentFilter() {
  return _currentFilter;
}

export function setCurrentFilter(filter) {
  _currentFilter = filter;
}

export function getCurrentSearch() {
  return _currentSearch;
}

export function setCurrentSearch(search) {
  _currentSearch = search;
}

export function getLastFleetData() {
  return _lastFleetData;
}

export function setLastFleetData(data) {
  _lastFleetData = data;
}

export function getModalReturnFocus() {
  return _modalReturnFocus;
}

export function setModalReturnFocus(el) {
  _modalReturnFocus = el;
}

export function getInventoryReturnFocus() {
  return _inventoryReturnFocus;
}

export function setInventoryReturnFocus(el) {
  _inventoryReturnFocus = el;
}

export function getInspectedOperationId() {
  return _inspectedOperationId;
}

export function setInspectedOperationId(id) {
  _inspectedOperationId = id;
}

export function trackActiveRequest(controller) {
  _activeRequests.add(controller);
}

export function removeActiveRequest(controller) {
  _activeRequests.delete(controller);
}

export function abortAllActiveRequests() {
  _activeRequests.forEach(controller => {
    try {
      controller.abort();
    } catch {
      // Ignore already aborted controllers
    }
  });
  _activeRequests.clear();
}
