// milestone-model.js — port of src/defender_acr_dashboard/milestone_analysis.py.
// Build a milestone gap model from two raw row arrays (Migration + Defender).
// Exposes window.MilestoneModel.

(() => {
  const MIGRATION_KIND = 'migration';
  const DEFENDER_KIND  = 'defender';
  const DEFAULT_NEAR_TERM_DAYS = 30;

  const REQUIRED_COLUMNS = {
    account:            ['Translated Account Name', 'Account name'],
    opportunity_id:     ['Opportunity ID'],
    milestone_id:       ['Milestone ID'],
    milestone_name:     ['Milestone Name'],
    milestone_workload: ['Milestone Workload'],
    workload:           ['Workload'],
    acr_pipeline:       ['ACR Pipeline $'],
    status:             ['Status'],
    commitment:         ['Commitment'],
    due_date:           ['Due Date', 'Estimated date'],
    category:           ['Category'],
    owner_role:         ['Owner Role'],
    owner:              ['Owner'],
  };

  const OPTIONAL_COLUMNS = {
    sales_stage: ['SalesStageName', 'Sales Stage Name', 'Sales Stage'],
  };

  const TEXT_COLUMNS = ['account','opportunity_id','milestone_id','milestone_name','milestone_workload','workload','status','commitment','category','owner_role','owner','sales_stage'];
  const TARGET_SALES_STAGE_KEYS = new Set(['inspire and design', 'listen and consult']);

  function loadMilestoneRecords(rows, datasetType, sourceFileName) {
    if (!Array.isArray(rows) || !rows.length) {
      throw new Error(`${sourceFileName}: workbook contains no rows.`);
    }
    const headerRow = rows[0] || [];
    const columnLookup = {};
    headerRow.forEach((cell, idx) => { columnLookup[normaliseKey(cell)] = idx; });

    const indexMap = {};
    for (const [target, candidates] of Object.entries(REQUIRED_COLUMNS)) {
      let foundIdx = -1;
      for (const name of candidates) {
        const k = normaliseKey(name);
        if (k in columnLookup) { foundIdx = columnLookup[k]; break; }
      }
      if (foundIdx < 0) {
        throw new Error(`${sourceFileName}: required column "${candidates.join('" or "')}" was not found.`);
      }
      indexMap[target] = foundIdx;
    }
    for (const [target, candidates] of Object.entries(OPTIONAL_COLUMNS)) {
      for (const name of candidates) {
        const k = normaliseKey(name);
        if (k in columnLookup) { indexMap[target] = columnLookup[k]; break; }
      }
    }

    const records = [];
    const dedupe = new Set();
    let invalidDates = 0;
    for (let r = 1; r < rows.length; r++) {
      const row = rows[r] || [];
      const rec = {
        dataset_type: datasetType,
        source_file: sourceFileName,
        source_row: r + 1,
      };
      for (const [target, idx] of Object.entries(indexMap)) {
        const raw = row[idx];
        if (target === 'acr_pipeline') {
          const n = typeof raw === 'number' ? raw : parseFloat(raw);
          rec[target] = Number.isFinite(n) ? n : 0;
        } else if (target === 'due_date') {
          rec[target] = parseDate(raw); // Date or null
        } else if (TEXT_COLUMNS.includes(target)) {
          rec[target] = cleanText(raw);
        } else {
          rec[target] = cleanText(raw);
        }
      }
      for (const target of Object.keys(OPTIONAL_COLUMNS)) {
        if (!(target in rec)) rec[target] = '';
      }
      rec.account_key      = key(rec.account);
      rec.opportunity_key  = key(rec.opportunity_id);
      rec.due_date_display = rec.due_date ? toIsoDate(rec.due_date) : '';
      if (rec.due_date == null && cleanText(row[indexMap.due_date]) !== '') {
        invalidDates++;
      }
      // Filter out non-customer / banner rows.
      if (!rec.account_key || rec.account_key === 'total' || rec.account_key.startsWith('applied filters:')) continue;
      const dk = dedupeKey(rec);
      if (dedupe.has(dk)) continue;
      dedupe.add(dk);
      records.push(rec);
    }
    records.sort((a, b) =>
      cmp(a.account, b.account) || cmp(a.opportunity_id, b.opportunity_id) || cmp(a.milestone_id, b.milestone_id)
    );
    records.invalidDates = invalidDates;
    return records;
  }

  function dedupeKey(rec) {
    if (rec.milestone_id) return `${rec.dataset_type}|milestone|${key(rec.milestone_id)}`;
    return [rec.dataset_type, rec.account_key, rec.opportunity_key, key(rec.milestone_name), key(rec.workload), rec.due_date_display].join('|');
  }

  function build(migrationRows, defenderRows, opts = {}) {
    const nearTermDays = Math.max(0, Math.trunc(opts.near_term_days ?? DEFAULT_NEAR_TERM_DAYS));
    // Stay on the UTC-midnight grid that stripTime() uses for due dates, so
    // priorityFor() compares like-with-like regardless of the user's timezone.
    let reference;
    if (opts.reference_date) {
      const parsed = new Date(opts.reference_date);
      reference = Number.isFinite(parsed.getTime()) ? stripTime(parsed) : startOfToday();
    } else {
      reference = startOfToday();
    }

    const migration = loadMilestoneRecords(migrationRows, MIGRATION_KIND, opts.migration_name || 'migration');
    const defender  = loadMilestoneRecords(defenderRows,  DEFENDER_KIND,  opts.defender_name  || 'defender');

    const migrationAccounts = new Set(migration.map(r => r.account_key));
    const defenderAccounts  = new Set(defender.map(r => r.account_key));
    const attached          = new Set([...migrationAccounts].filter(a => defenderAccounts.has(a)));
    const migrationOnly     = new Set([...migrationAccounts].filter(a => !defenderAccounts.has(a)));
    const defenderOppPairs  = new Set(defender.map(r => `${r.account_key}::${r.opportunity_key}`));

    const gapRows = [];
    for (const rec of migration) {
      if (migrationOnly.has(rec.account_key)) {
        gapRows.push({ ...rec, gap_type: 'Account-level gap' });
      }
    }
    for (const rec of migration) {
      if (!attached.has(rec.account_key)) continue;
      if (!defenderOppPairs.has(`${rec.account_key}::${rec.opportunity_key}`)) {
        gapRows.push({ ...rec, gap_type: 'Opportunity-level gap' });
      }
    }

    const gaps = aggregate(gapRows, reference, nearTermDays);
    const priorityRank = { HIGH: 0, MEDIUM: 1, LOW: 2 };
    gaps.sort((a, b) =>
      priorityRank[a.priority] - priorityRank[b.priority] ||
      cmp(a.estimated_date || '9999-12-31', b.estimated_date || '9999-12-31') ||
      (b.acr_pipeline - a.acr_pipeline)
    );

    const accountGapKeys = new Set(gaps.map(g => g.account_key));
    const opportunityGapKeys = new Set(gaps.map(g => `${g.account_key}|${g.opportunity_id || ''}`));
    const priorityCounts = countBy(gaps, 'priority', ['HIGH', 'MEDIUM', 'LOW']);
    const gapTypeCounts  = countBy(gaps, 'gap_type', ['Account-level gap', 'Opportunity-level gap']);
    const workloadCounts = topWorkloadCounts(gaps);

    return {
      summary: {
        migration_accounts: migrationAccounts.size,
        defender_accounts:  defenderAccounts.size,
        attached_accounts:  attached.size,
        account_level_gap_accounts: migrationOnly.size,
        total_accounts_with_gaps: accountGapKeys.size,
        total_opportunities_with_gaps: opportunityGapKeys.size,
        account_level_gaps: gapTypeCounts['Account-level gap'],
        opportunity_level_gaps: gapTypeCounts['Opportunity-level gap'],
        total_gap_rows: gaps.length,
      },
      priority_counts: priorityCounts,
      gap_type_counts: gapTypeCounts,
      workload_counts: workloadCounts,
      gaps,
      top_gaps: gaps.slice(0, 10),
      data_quality: {
        migration_rows: migration.length,
        defender_rows:  defender.length,
        migration_invalid_dates: migration.invalidDates || 0,
        defender_invalid_dates:  defender.invalidDates  || 0,
        strict_opportunity_match: 'Migration opportunities are compared to Defender milestones only when account and Opportunity ID both match.',
      },
      sources: { migration: opts.migration_name || '', defender: opts.defender_name || '' },
      near_term_days: nearTermDays,
      reference_date: toIsoDate(reference),
    };
  }

  function aggregate(rows, reference, nearTermDays) {
    const groups = new Map();
    for (const r of rows) {
      const k = `${r.account_key}||${r.opportunity_key}||${r.gap_type}`;
      let g = groups.get(k);
      if (!g) { g = []; groups.set(k, g); }
      g.push(r);
    }
    const output = [];
    for (const group of groups.values()) {
      const displayAccount = firstNonEmpty(group.map(r => r.account));
      const opportunityId  = firstNonEmpty(group.map(r => r.opportunity_id));
      const workloads      = uniqueText(group.map(r => r.workload));
      const milestoneLoads = uniqueText(group.map(r => r.milestone_workload));
      const commitments    = uniqueText(group.map(r => r.commitment));
      const statuses       = uniqueText(group.map(r => r.status));
      const salesStages    = uniqueText(group.map(r => r.sales_stage));
      const owners         = uniqueText(group.map(r => r.owner));
      const ownerRoles     = uniqueText(group.map(r => r.owner_role));
      const dueDates = group.map(r => r.due_date).filter(Boolean).sort((a, b) => a - b);
      const earliestDue = dueDates.length ? dueDates[0] : null;
      const hasCommitted = group.some(r => key(r.commitment) === 'committed');
      const hasValidWorkload = workloads.some(isValidWorkload);
      const [priority, reason] = priorityFor({ salesStages, hasValidWorkload });
      const milestoneIds = new Set(group.map(r => r.milestone_id).filter(Boolean));
      output.push({
        account_key: group[0].account_key,
        account: displayAccount,
        opportunity_id: opportunityId,
        gap_type: group[0].gap_type,
        workload: workloads.length ? workloads.join('; ') : 'Unclear workload',
        milestone_workload: milestoneLoads.join('; '),
        estimated_date: earliestDue ? toIsoDate(earliestDue) : '',
        priority,
        commitment: commitments.join('; '),
        status: statuses.join('; '),
        sales_stage: salesStages.join('; '),
        acr_pipeline: round2(group.reduce((s, r) => s + (r.acr_pipeline || 0), 0)),
        owner_role: ownerRoles.join('; '),
        owner: owners.join('; '),
        milestone_count: milestoneIds.size || group.length,
        has_committed: hasCommitted,
        priority_reason: reason,
        milestones: uniqueText(group.map(r => r.milestone_name)).slice(0, 6),
      });
    }
    return output;
  }

  function priorityFor({ salesStages, hasValidWorkload }) {
    const targetStage = salesStages.find(stage => TARGET_SALES_STAGE_KEYS.has(salesStageKey(stage)));
    if (targetStage) return ['HIGH', `Target sales stage: ${targetStage}`];
    if (salesStages.length) return ['MEDIUM', `Other sales stage: ${salesStages.join('; ')}`];
    if (hasValidWorkload) return ['MEDIUM', 'No sales stage provided; valid workload'];
    return ['LOW', 'No target sales stage and unclear workload'];
  }

  function salesStageKey(value) {
    return key(value).replace(/&/g, ' and ').replace(/\s+/g, ' ').trim();
  }

  function isValidWorkload(text) {
    const k = key(text);
    if (!k) return false;
    return !['unknown', 'unclear', 'tbd', 'to be scoped', 'placeholder', 'other adjustment'].some(t => k.includes(t));
  }

  function topWorkloadCounts(gaps, limit = 10) {
    const counts = new Map();
    for (const row of gaps) {
      for (const part of String(row.workload).split(';')) {
        const w = part.trim();
        if (!w) continue;
        counts.set(w, (counts.get(w) || 0) + 1);
      }
    }
    return [...counts.entries()]
      .sort((a, b) => (b[1] - a[1]) || cmp(a[0], b[0]))
      .slice(0, limit)
      .map(([workload, count]) => ({ workload, count }));
  }

  function countBy(rows, k, expected) {
    const out = Object.fromEntries(expected.map(v => [v, 0]));
    for (const r of rows) {
      const v = r[k];
      out[v] = (out[v] || 0) + 1;
    }
    return out;
  }

  function firstNonEmpty(values) { for (const v of values) { const t = cleanText(v); if (t) return t; } return ''; }
  function uniqueText(values) {
    const seen = new Set(); const output = [];
    for (const v of values) { const t = cleanText(v); const k = key(t); if (t && !seen.has(k)) { seen.add(k); output.push(t); } }
    return output;
  }

  function cleanText(value) {
    if (value == null) return '';
    if (value instanceof Date) return toIsoDate(value);
    let text = String(value).replace(/\u00a0/g, ' ').trim();
    if (/^\d+\.0$/.test(text)) text = text.slice(0, -2);
    return text.replace(/\s+/g, ' ');
  }

  function key(value) { return cleanText(value).toLowerCase(); }
  function normaliseKey(value) { return cleanText(value).toLowerCase(); }

  function parseDate(value) {
    if (value == null || value === '') return null;
    if (value instanceof Date) return Number.isFinite(value.getTime()) ? stripTime(value) : null;
    if (typeof value === 'number' && Number.isFinite(value)) {
      // Treat as Excel serial date when in plausible range; otherwise as ms since epoch is unlikely.
      if (value >= 20000 && value <= 80000) {
        // Excel epoch (Lotus 1-2-3 compatibility): 1899-12-30 (UTC).
        const ms = Math.round((value - 25569) * 86400 * 1000);
        const d = new Date(ms);
        return stripTime(d);
      }
      return null;
    }
    const parsed = new Date(value);
    return Number.isFinite(parsed.getTime()) ? stripTime(parsed) : null;
  }

  function stripTime(d) {
    // Work in UTC so the ISO date matches the spreadsheet's calendar date regardless of TZ.
    return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()));
  }

  function toIsoDate(d) { return d.toISOString().slice(0, 10); }

  function startOfToday() { const d = new Date(); return new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate())); }

  function cmp(a, b) { a = a || ''; b = b || ''; return a < b ? -1 : a > b ? 1 : 0; }
  function round2(value) { const n = Number(value || 0); return Number.isFinite(n) ? Math.round(n * 100) / 100 : 0; }

  window.MilestoneModel = { build, DEFAULT_NEAR_TERM_DAYS };
})();
