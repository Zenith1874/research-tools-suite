(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.GdpSeries = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  function realGrowthRows(rows) {
    const direct = rows.filter(row => row.indicator_code === 'real_growth' && Number.isFinite(row.value));
    const seen = new Set(direct.map(row => row.region_code + '|' + row.period));
    const groups = new Map();
    for (const row of rows) {
      if (row.indicator_code !== 'real_gdp' || !Number.isFinite(row.value) || row.value <= 0 || !/^\d{4}$/.test(row.period)) continue;
      if (!groups.has(row.region_code)) groups.set(row.region_code, []);
      groups.get(row.region_code).push(row);
    }
    const result = direct.slice();
    for (const history of groups.values()) {
      history.sort((a, b) => a.period.localeCompare(b.period));
      for (let index = 1; index < history.length; index += 1) {
        const current = history[index], previous = history[index - 1];
        const key = current.region_code + '|' + current.period;
        // Do not bridge missing years or a change in chained-price units.
        if (seen.has(key) || Number(current.period) !== Number(previous.period) + 1 || current.unit !== previous.unit) continue;
        result.push({...current, indicator_code: 'real_growth', value: (current.value / previous.value - 1) * 100,
          unit: '%', data_status: 'derived', parser_notes: '相邻完整年度、同价格基期实际GDP之比减一；官方直接公布增速优先。'});
        seen.add(key);
      }
    }
    return result.sort((a, b) => a.period.localeCompare(b.period) || a.region_code.localeCompare(b.region_code));
  }

  function enrichProvenance(rows, snapshot) {
    const indexed = new Map((snapshot?.rows || []).map(row => [row.region_code + '|' + row.indicator_code + '|' + row.period, row]));
    return rows.map(row => {
      const source = indexed.get(row.region_code + '|' + row.indicator_code + '|' + row.period);
      // Older live APIs omit provenance; attach only a reviewed exact-value match.
      if (!row.source_url && source && row.value === source.value && row.unit === source.unit) return {...source, ...row,
        source_url: source.source_url, source_name: source.source_name, data_status: source.data_status,
        parser_notes: source.parser_notes, access_type: source.access_type};
      return row;
    });
  }

  function comparisonPointRadii(values, selectedCount) {
    // An isolated observation has no line segment; never hide its only mark.
    return values.map((value, index) => {
      if (!Number.isFinite(value)) return 0;
      if (!Number.isFinite(values[index - 1]) && !Number.isFinite(values[index + 1])) return 4;
      return selectedCount <= 3 ? 2 : 0;
    });
  }

  function annualComparisonYears(periods, start, end) {
    const observed = periods.filter(period => /^\d{4}$/.test(period)
      && (!start || period >= start) && (!end || period <= end)).map(Number);
    if (!observed.length) return [];
    const first = Math.min(...observed), last = Math.max(...observed);
    // Empty axis years create nulls, not observations or interpolated values.
    return Array.from({length: last - first + 1}, (_, index) => String(first + index));
  }

  return {realGrowthRows, enrichProvenance, comparisonPointRadii, annualComparisonYears};
});
