/**
 * Auto-refresh timer for the serverless job list.
 * Active only when the orchestratorServerless tab is visible.
 */
let serverlessRefreshInterval = null;

/**
 * Start auto-refreshing the serverless job list every 5 seconds.
 * Clears any existing interval before starting a new one.
 */
function startServerlessAutoRefresh() {
    stopServerlessAutoRefresh();
    // Load available links on tab activation
    loadServerlessLinks();
    serverlessRefreshInterval = setInterval(function() {
        refreshJobList();
        loadServerlessMetrics();
        loadServerlessLinks();
    }, 5000);
}

/**
 * Stop the auto-refresh timer for the serverless job list.
 */
function stopServerlessAutoRefresh() {
    if (serverlessRefreshInterval !== null) {
        clearInterval(serverlessRefreshInterval);
        serverlessRefreshInterval = null;
    }
}

/**
 * Load available agentic-ai-plateform-serverless-brik endpoint links into the target dropdown
 * and display them in the links panel with availability status.
 * Preserves the currently selected value in the dropdown.
 */
async function loadServerlessLinks() {
    const select = document.getElementById('serverlessTargetLink');
    const linksContent = document.getElementById('serverlessLinksContent');

    // Preserve current selection before rebuilding
    const previousSelection = select ? select.value : '';

    try {
        const response = await fetch('/api/serverless-links', {
            method: 'GET',
            credentials: 'same-origin'
        });

        if (!response.ok) {
            if (select) select.innerHTML = '<option value="">-- Failed to load links --</option>';
            if (linksContent) linksContent.innerHTML = '<p style="color:red;">Failed to load endpoints.</p>';
            return;
        }

        const data = await response.json();
        const endpoints = data.endpoints || [];
        const links = data.links || [];

        if (endpoints.length === 0 && links.length === 0) {
            if (select) select.innerHTML = '<option value="">-- No endpoints available --</option>';
            if (linksContent) linksContent.innerHTML = '<p style="color:orange;">No agentic-ai-plateform-serverless-brik endpoints are currently assigned. Please contact your administrator.</p>';
            return;
        }

        // Use endpoints (with status) if available, otherwise fall back to flat links
        if (endpoints.length > 0) {
            // Populate dropdown with status indicators
            if (select) {
                let selectHtml = '<option value="">-- Select target endpoint --</option>';
                for (const ep of endpoints) {
                    const statusLabel = ep.status === 'AVAILABLE' ? '✅' : ep.status === 'OCCUPIED' ? '🔒' : '❓';
                    const disabled = ep.status === 'OCCUPIED' ? ' disabled' : '';
                    const selected = (ep.url === previousSelection) ? ' selected' : '';
                    selectHtml += '<option value="' + ep.url + '"' + disabled + selected + '>' + statusLabel + ' ' + ep.url + ' (' + ep.username + ') - ' + ep.status + '</option>';
                }
                select.innerHTML = selectHtml;
            }

            // Populate links panel with status badges
            if (linksContent) {
                let panelHtml = '<table style="width:100%; border-collapse:collapse;">';
                panelHtml += '<tr style="border-bottom:1px solid #ddd;"><th style="text-align:left; padding:5px;">Endpoint</th><th style="text-align:left; padding:5px;">Owner</th><th style="text-align:left; padding:5px;">Status</th></tr>';
                for (const ep of endpoints) {
                    let statusBadge;
                    if (ep.status === 'AVAILABLE') {
                        statusBadge = '<span style="background:#28a745; color:#fff; padding:2px 8px; border-radius:3px; font-size:12px;">✅ AVAILABLE</span>';
                    } else if (ep.status === 'OCCUPIED') {
                        statusBadge = '<span style="background:#dc3545; color:#fff; padding:2px 8px; border-radius:3px; font-size:12px;">🔒 OCCUPIED</span>';
                    } else {
                        statusBadge = '<span style="background:#6c757d; color:#fff; padding:2px 8px; border-radius:3px; font-size:12px;">❓ UNKNOWN</span>';
                    }
                    panelHtml += '<tr style="border-bottom:1px solid #eee;">';
                    panelHtml += '<td style="padding:5px;"><a href="' + ep.url + '" target="_blank" style="color:#007bff; text-decoration:none;">' + ep.url + '</a></td>';
                    panelHtml += '<td style="padding:5px;">' + ep.username + '</td>';
                    panelHtml += '<td style="padding:5px;">' + statusBadge + '</td>';
                    panelHtml += '</tr>';
                }
                panelHtml += '</table>';
                linksContent.innerHTML = panelHtml;
            }
        } else {
            // Fallback: use flat links without status
            if (select) {
                let selectHtml = '<option value="">-- Select target endpoint --</option>';
                for (const link of links) {
                    const selected = (link === previousSelection) ? ' selected' : '';
                    selectHtml += '<option value="' + link + '"' + selected + '>' + link + '</option>';
                }
                select.innerHTML = selectHtml;
            }
            if (linksContent) {
                let panelHtml = '<ul style="list-style: none; padding: 0; margin: 0;">';
                for (const link of links) {
                    panelHtml += '<li style="margin-bottom: 5px;"><a href="' + link + '" target="_blank" style="color:#007bff; text-decoration:none;">🌐 ' + link + '</a></li>';
                }
                panelHtml += '</ul>';
                linksContent.innerHTML = panelHtml;
            }
        }
    } catch (err) {
        if (select) select.innerHTML = '<option value="">-- Error loading links --</option>';
        if (linksContent) linksContent.innerHTML = '<p style="color:red;">Network error: ' + err.message + '</p>';
    }
}

/**
 * Submit a serverless Docker job via POST /api/jobs.
 * Reads form inputs, builds the payload, and refreshes the job list on success.
 */
async function submitServerlessJob() {
    const targetLink = document.getElementById('serverlessTargetLink').value;
    const image = document.getElementById('serverlessImage').value.trim();
    const commandStr = document.getElementById('serverlessCommand').value.trim();
    const envStr = document.getElementById('serverlessEnv').value.trim();
    const timeoutStr = document.getElementById('serverlessTimeout').value.trim();

    // Validate required fields
    if (!targetLink) {
        alert('Error: You must select a target endpoint.');
        return;
    }
    if (!image) {
        alert('Error: Docker image is required.');
        return;
    }
    if (!commandStr) {
        alert('Error: Command is required.');
        return;
    }

    // Parse command: each line is a separate command entry
    // Split by newlines, trim each line, filter out empty lines
    const lines = commandStr.split(/\r?\n/).map(line => line.trim()).filter(line => line.length > 0);
    const command = lines;

    // Build the request payload
    const payload = {
        image: image,
        command: command,
        target_link: targetLink
    };

    // Parse environment variables JSON if provided
    if (envStr) {
        try {
            const env = JSON.parse(envStr);
            payload.env = env;
        } catch (e) {
            alert('Error: Environment variables must be valid JSON.\n' + e.message);
            return;
        }
    }

    // Include timeout if provided
    if (timeoutStr) {
        const timeout = parseInt(timeoutStr, 10);
        if (isNaN(timeout) || timeout < 1 || timeout > 3600) {
            alert('Error: Timeout must be between 1 and 3600 seconds.');
            return;
        }
        payload.timeout = timeout;
    }

    try {
        const response = await fetch('/api/jobs', {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });

        if (response.ok) {
            const data = await response.json();
            alert('Job submitted successfully! Job ID: ' + data.job_id);
            // Reset the form
            document.getElementById('serverlessJobForm').reset();
            // Re-load links after form reset (reset clears the dropdown)
            loadServerlessLinks();
            // Refresh the job list
            if (typeof refreshJobList === 'function') {
                refreshJobList();
            }
        } else {
            const errorData = await response.json().catch(() => null);
            const errorMsg = errorData && errorData.error ? errorData.error : 'HTTP ' + response.status;
            alert('Failed to submit job: ' + errorMsg);
        }
    } catch (err) {
        alert('Network error submitting job: ' + err.message);
    }
}

function formatRepoSize(sizeInMB) {
    if (sizeInMB < 10) {
        return `Small (${sizeInMB}MB)`;
    } else if (sizeInMB < 100) {
        return `Medium (${sizeInMB}MB)`;
    } else if (sizeInMB < 1000) {
        return `Large (${sizeInMB}MB)`;
    } else {
        return `Very Large (${(sizeInMB/1000).toFixed(1)}GB)`;
    }
}

function startCloneProgressSimulation(repoSizeMB) {
    let progress = 0;
    let startTime = Date.now();
    
    // Calculate estimated duration based on actual repo size
    let estimatedDuration;
    if (repoSizeMB < 10) {
        estimatedDuration = 15 + (repoSizeMB * 1.5); // 15-30 seconds
    } else if (repoSizeMB < 100) {
        estimatedDuration = 30 + (repoSizeMB * 0.8); // 30-110 seconds
    } else if (repoSizeMB < 1000) {
        estimatedDuration = 120 + (repoSizeMB * 0.3); // 2-7 minutes
    } else {
        estimatedDuration = 300 + (repoSizeMB * 0.1); // 5+ minutes
    }
    
    // Set initial estimated time
    document.getElementById('estimatedTime').textContent = formatDuration(Math.round(estimatedDuration));
    
    const progressInterval = setInterval(() => {
        const elapsed = Math.floor((Date.now() - startTime) / 1000);
        document.getElementById('elapsedTime').textContent = elapsed + 's';
        
        // Simulate realistic progress curve (slower at start, faster in middle, slower at end)
        const timeRatio = elapsed / estimatedDuration;
        if (timeRatio < 0.1) {
            progress = timeRatio * 50; // 0-5% in first 10% of time
        } else if (timeRatio < 0.8) {
            progress = 5 + (timeRatio - 0.1) * 128.57; // 5-95% in next 70% of time
        } else {
            progress = 95 + (timeRatio - 0.8) * 25; // 95-100% in last 20% of time
        }
        
        progress = Math.min(progress, 99); // Never reach 100% until actually done
        
        const progressBar = document.getElementById('cloneProgress');
        const progressText = document.getElementById('progressText');
        
        if (progressBar) {
            progressBar.style.width = progress + '%';
        }
        
        if (progressText) {
            if (progress < 10) {
                progressText.textContent = 'Connecting to repository...';
            } else if (progress < 30) {
                progressText.textContent = 'Downloading repository metadata...';
            } else if (progress < 70) {
                progressText.textContent = 'Cloning files and history...';
            } else if (progress < 90) {
                progressText.textContent = 'Processing repository structure...';
            } else {
                progressText.textContent = 'Finalizing clone operation...';
            }
        }
        
        // Update estimated time remaining
        const remaining = Math.max(0, estimatedDuration - elapsed);
        if (remaining > 0) {
            document.getElementById('estimatedTime').textContent = formatDuration(remaining) + ' remaining';
        }
        
    }, 1000);
    
    // Store interval ID to clear it later
    window.cloneProgressInterval = progressInterval;
}


/**
 * Refresh the serverless jobs list by fetching from GET /api/jobs
 * and rendering the job table with status badges and action buttons.
 */
async function refreshJobList() {
    const tbody = document.getElementById('serverlessJobsBody');
    if (!tbody) return;

    try {
        const response = await fetch('/api/jobs', {
            method: 'GET',
            credentials: 'same-origin'
        });

        if (!response.ok) {
            tbody.innerHTML = '<tr><td colspan="6">Failed to load jobs (HTTP ' + response.status + ')</td></tr>';
            return;
        }

        const data = await response.json();
        const jobs = data.jobs || [];

        if (jobs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6">No jobs found</td></tr>';
            return;
        }

        let html = '';
        for (const job of jobs) {
            const createdAt = job.created_at ? new Date(job.created_at).toLocaleString() : 'N/A';
            const statusBadge = '<span class="job-status-badge status-' + job.status + '">' + job.status + '</span>';
            const targetLink = job.target_link || 'N/A';

            let actions = '<button class="btn btn-secondary btn-small" onclick="viewJobDetail(\'' + job.job_id + '\')">View</button>';
            if (job.status === 'pending' || job.status === 'running') {
                actions += ' <button class="btn btn-danger btn-small" onclick="cancelJob(\'' + job.job_id + '\')">Cancel</button>';
            }

            html += '<tr>';
            html += '<td>' + job.job_id + '</td>';
            html += '<td>' + job.image + '</td>';
            html += '<td><a href="' + targetLink + '" target="_blank" style="color:#007bff;">' + targetLink + '</a></td>';
            html += '<td>' + statusBadge + '</td>';
            html += '<td>' + createdAt + '</td>';
            html += '<td>' + actions + '</td>';
            html += '</tr>';
        }

        tbody.innerHTML = html;
    } catch (err) {
        tbody.innerHTML = '<tr><td colspan="6">Network error loading jobs: ' + err.message + '</td></tr>';
    }
}

/**
 * View job detail by fetching job status and result from the API,
 * then displaying the information in the detail panel.
 * @param {string} jobId - The UUID of the job to view
 */
async function viewJobDetail(jobId) {
    const detailPanel = document.getElementById('serverlessJobDetail');
    const detailContent = document.getElementById('serverlessJobDetailContent');

    if (!detailPanel || !detailContent) return;

    // Show the panel and indicate loading
    detailPanel.style.display = 'block';
    detailContent.innerHTML = '<p>Loading job details...</p>';

    try {
        // Fetch job status
        const statusResponse = await fetch('/api/jobs/' + jobId, {
            method: 'GET',
            credentials: 'same-origin'
        });

        if (!statusResponse.ok) {
            const errData = await statusResponse.json().catch(() => null);
            const errMsg = errData && errData.error ? errData.error : 'HTTP ' + statusResponse.status;
            detailContent.innerHTML = '<p style="color:red;">Failed to load job details: ' + errMsg + '</p>';
            return;
        }

        const job = await statusResponse.json();

        // Build job metadata HTML
        let html = '<table class="job-detail-table" style="width:100%; border-collapse:collapse; margin-bottom:15px;">';
        html += '<tr><td><strong>Job ID:</strong></td><td>' + (job.job_id || jobId) + '</td></tr>';
        html += '<tr><td><strong>Status:</strong></td><td><span class="job-status-badge status-' + job.status + '">' + job.status + '</span></td></tr>';
        html += '<tr><td><strong>Image:</strong></td><td>' + (job.image || 'N/A') + '</td></tr>';
        html += '<tr><td><strong>Created:</strong></td><td>' + (job.created_at ? new Date(job.created_at).toLocaleString() : 'N/A') + '</td></tr>';
        html += '<tr><td><strong>Started:</strong></td><td>' + (job.started_at ? new Date(job.started_at).toLocaleString() : 'N/A') + '</td></tr>';
        html += '<tr><td><strong>Completed:</strong></td><td>' + (job.completed_at ? new Date(job.completed_at).toLocaleString() : 'N/A') + '</td></tr>';
        html += '<tr><td><strong>Exit Code:</strong></td><td>' + (job.exit_code !== null && job.exit_code !== undefined ? job.exit_code : 'N/A') + '</td></tr>';
        html += '<tr><td><strong>Worker:</strong></td><td>' + (job.worker_id || 'N/A') + '</td></tr>';
        html += '</table>';

        // If job is in a terminal state, fetch the result
        const terminalStates = ['completed', 'failed', 'timeout', 'cancelled'];
        if (terminalStates.includes(job.status)) {
            try {
                const resultResponse = await fetch('/api/jobs/' + jobId + '/result', {
                    method: 'GET',
                    credentials: 'same-origin'
                });

                if (resultResponse.ok) {
                    const result = await resultResponse.json();

                    html += '<h4 style="margin-top:10px;">Result</h4>';
                    html += '<p><strong>Exit Code:</strong> ' + (result.exit_code !== null && result.exit_code !== undefined ? result.exit_code : 'N/A') + '</p>';

                    if (result.stdout) {
                        html += '<h5>Stdout:</h5>';
                        html += '<pre style="background:#1e1e1e; color:#d4d4d4; padding:10px; border-radius:4px; overflow-x:auto; max-height:300px; overflow-y:auto;">' + escapeHtml(result.stdout) + '</pre>';
                    }

                    if (result.stderr) {
                        html += '<h5>Stderr:</h5>';
                        html += '<pre style="background:#2d1515; color:#f48771; padding:10px; border-radius:4px; overflow-x:auto; max-height:300px; overflow-y:auto;">' + escapeHtml(result.stderr) + '</pre>';
                    }

                    if (result.result && Object.keys(result.result).length > 0) {
                        html += '<h5>Structured Result:</h5>';
                        html += '<pre style="background:#f8f9fa; padding:10px; border-radius:4px; overflow-x:auto;">' + escapeHtml(JSON.stringify(result.result, null, 2)) + '</pre>';
                    }
                } else if (resultResponse.status !== 409) {
                    // 409 means job not in terminal state (shouldn't happen here), other errors we show
                    html += '<p style="color:orange;">Could not load job result (HTTP ' + resultResponse.status + ')</p>';
                }
            } catch (resultErr) {
                html += '<p style="color:orange;">Network error loading result: ' + resultErr.message + '</p>';
            }
        }

        detailContent.innerHTML = html;
    } catch (err) {
        detailContent.innerHTML = '<p style="color:red;">Network error loading job details: ' + err.message + '</p>';
    }
}

/**
 * Cancel a serverless job by POSTing to /api/jobs/{id}/cancel.
 * Shows a confirmation dialog before proceeding.
 * @param {string} jobId - The UUID of the job to cancel
 */
async function cancelJob(jobId) {
    if (!confirm('Are you sure you want to cancel this job?')) {
        return;
    }

    try {
        const response = await fetch('/api/jobs/' + jobId + '/cancel', {
            method: 'POST',
            credentials: 'same-origin'
        });

        if (response.ok) {
            alert('Job cancelled successfully.');
            refreshJobList();
        } else {
            const errorData = await response.json().catch(() => null);
            const errorMsg = errorData && errorData.error ? errorData.error : 'HTTP ' + response.status;
            if (response.status === 409) {
                alert('Cannot cancel job: ' + errorMsg);
            } else {
                alert('Failed to cancel job: ' + errorMsg);
            }
        }
    } catch (err) {
        alert('Network error cancelling job: ' + err.message);
    }
}

/**
 * Load serverless job metrics from GET /api/jobs/metrics (admin-only)
 * and render the metrics panel with styled metric cards.
 */
async function loadServerlessMetrics() {
    const content = document.getElementById('serverlessMetricsContent');
    if (!content) return;

    try {
        const response = await fetch('/api/jobs/metrics', {
            method: 'GET',
            credentials: 'same-origin'
        });

        if (response.status === 403) {
            content.innerHTML = '<p style="color:#666; font-style:italic;">Metrics are available to administrators only.</p>';
            return;
        }

        if (!response.ok) {
            content.innerHTML = '<p style="color:red;">Failed to load metrics (HTTP ' + response.status + ')</p>';
            return;
        }

        const data = await response.json();

        const avgExec = data.avg_execution_time !== null ? data.avg_execution_time + 's' : 'N/A';
        const avgStartup = data.avg_startup_duration !== null ? data.avg_startup_duration + 's' : 'N/A';

        let html = '<div style="display:flex; flex-wrap:wrap; gap:15px;">';

        html += '<div style="flex:1; min-width:120px; padding:12px; background:#fff; border-radius:6px; border:1px solid #e0e0e0; text-align:center;">';
        html += '<div style="font-size:24px; font-weight:bold; color:#6c757d;">' + data.pending_count + '</div>';
        html += '<div style="font-size:12px; color:#888;">Pending</div>';
        html += '</div>';

        html += '<div style="flex:1; min-width:120px; padding:12px; background:#fff; border-radius:6px; border:1px solid #e0e0e0; text-align:center;">';
        html += '<div style="font-size:24px; font-weight:bold; color:#007bff;">' + data.running_count + '</div>';
        html += '<div style="font-size:12px; color:#888;">Running</div>';
        html += '</div>';

        html += '<div style="flex:1; min-width:120px; padding:12px; background:#fff; border-radius:6px; border:1px solid #e0e0e0; text-align:center;">';
        html += '<div style="font-size:24px; font-weight:bold; color:#dc3545;">' + data.failed_count + '</div>';
        html += '<div style="font-size:12px; color:#888;">Failed</div>';
        html += '</div>';

        html += '<div style="flex:1; min-width:120px; padding:12px; background:#fff; border-radius:6px; border:1px solid #e0e0e0; text-align:center;">';
        html += '<div style="font-size:24px; font-weight:bold; color:#28a745;">' + avgExec + '</div>';
        html += '<div style="font-size:12px; color:#888;">Avg Execution</div>';
        html += '</div>';

        html += '<div style="flex:1; min-width:120px; padding:12px; background:#fff; border-radius:6px; border:1px solid #e0e0e0; text-align:center;">';
        html += '<div style="font-size:24px; font-weight:bold; color:#6c757d;">' + data.queue_depth + '</div>';
        html += '<div style="font-size:12px; color:#888;">Queue Depth</div>';
        html += '</div>';

        html += '<div style="flex:1; min-width:120px; padding:12px; background:#fff; border-radius:6px; border:1px solid #e0e0e0; text-align:center;">';
        html += '<div style="font-size:24px; font-weight:bold; color:#17a2b8;">' + avgStartup + '</div>';
        html += '<div style="font-size:12px; color:#888;">Avg Startup</div>';
        html += '</div>';

        html += '</div>';

        content.innerHTML = html;
    } catch (err) {
        content.innerHTML = '<p style="color:red;">Network error loading metrics: ' + err.message + '</p>';
    }
}

/**
 * Escape HTML special characters to prevent XSS when displaying user content.
 * @param {string} text - The text to escape
 * @returns {string} The escaped text
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(text));
    return div.innerHTML;
}
/* ------------------------------------------------------------------------- *
 * Sortable table headers (Sort_Helper)                                        *
 *                                                                             *
 * Reusable click-to-sort helper attached to dashboard tables. This is a       *
 * UI-only feature: it reorders already-rendered <tbody> rows in place and     *
 * issues no data requests.                                                    *
 *                                                                             *
 * NOTE: The functions below are STUBS added in task 1.1. Real logic is filled *
 * in by later tasks (2.x - 6.x). They are intentionally minimal placeholders. *
 * ------------------------------------------------------------------------- */

/**
 * Attach click-to-sort behavior to a rendered table.
 *
 * @param {HTMLTableElement|null} table - the table produced by a render function.
 *        If null or without a <thead>/<tbody>, the call is a no-op.
 * @param {Object} [options]
 * @param {number[]} [options.excludeColumns] - additional zero-based column indices to
 *        exclude from sorting (beyond the auto-detected trailing Actions column).
 * @param {string[]} [options.actionHeaderLabels] - header texts (case-insensitive) that
 *        mark a non-sortable Actions column. Defaults to ['actions'] plus the localized
 *        "actions" label used by the templates.
 * @returns {void}
 */
function makeSortable(table, options) {
    // Guard/no-op when the table, its <thead>, or its <tbody> rows are absent
    // (Requirement 6.1 error handling; design "No table / empty table").
    if (!table || !table.querySelector) return;
    if (!table.querySelector('thead')) return;
    const tbody = table.querySelector('tbody');
    if (!tbody || !tbody.querySelector('tr')) return;

    // Store options on the element so applySort/updateIndicators resolve headers
    // with the same exclusion rules via table._sortOptions.
    const opts = options || {};
    table._sortOptions = opts;

    // Per-table sort state: null column and 'asc' until the first click. Storing
    // it on the element means re-rendering a panel naturally resets the state.
    table._sortState = { colIndex: null, dir: 'asc' };

    // Resolve per-column metadata (which headers are sortable vs excluded).
    const headers = resolveHeaders(table, opts);

    headers.forEach(function (h) {
        // Excluded headers (trailing Actions column, options.excludeColumns) get
        // no listener, no pointer cursor, and no indicator span (Req 1.4, 4.2).
        if (!h.sortable) return;

        const th = h.th;
        const colIndex = h.index;

        // Wrap the label once in a dedicated <span class="sort-indicator"> so the
        // arrow lives in its own span; the label text is kept intact and the empty
        // indicator span is appended after it (design "Implementation detail").
        if (!th.querySelector('span.sort-indicator')) {
            const span = th.ownerDocument.createElement('span');
            span.className = 'sort-indicator';
            th.appendChild(span);
        }

        // Visual affordance and machine-readable marker for sortable headers.
        th.style.cursor = 'pointer';
        th.setAttribute('data-sortable', 'true');

        // Click sorts by this column (Req 1.1); no sort/indicator at attach time
        // preserves the initial order (Req 4.1, 4.2).
        th.addEventListener('click', function () {
            applySort(table, colIndex);
        });
    });
}

/**
 * Locate the table's <th> cells and decide which are sortable, marking the
 * trailing Actions column and any options.excludeColumns indices as excluded.
 *
 * @param {HTMLTableElement} table
 * @param {Object} [options]
 * @param {number[]} [options.excludeColumns] - additional zero-based indices to exclude.
 * @param {string[]} [options.actionHeaderLabels] - header texts (case-insensitive) that
 *        mark a non-sortable trailing Actions column. Defaults to ['actions'].
 * @returns {Array<{index:number, sortable:boolean, excluded:boolean, th:HTMLTableCellElement}>}
 */
function resolveHeaders(table, options) {
    const opts = options || {};

    // Header texts (lower-cased) that mark a non-sortable trailing Actions column.
    // Defaults to ['actions'] plus any localized label the templates render for
    // get_text('actions'); callers may override/extend via options.actionHeaderLabels.
    const actionLabels = (opts.actionHeaderLabels || ['actions']).map(function (label) {
        return String(label).trim().toLowerCase();
    });

    // Additional zero-based column indices to exclude from sorting.
    const excludeSet = {};
    (opts.excludeColumns || []).forEach(function (idx) {
        excludeSet[idx] = true;
    });

    // Locate the <th> cells. Prefer the header row so stray body <th> cells are ignored.
    let ths = [];
    if (table && table.querySelectorAll) {
        const headRow = table.querySelector('thead tr');
        if (headRow) {
            ths = Array.prototype.slice.call(headRow.querySelectorAll('th'));
        } else {
            ths = Array.prototype.slice.call(table.querySelectorAll('th'));
        }
    }

    // Determine the trailing Actions column: the last <th> whose lower-cased text
    // matches one of the action labels. Only the trailing header qualifies.
    let actionsIndex = -1;
    if (ths.length > 0) {
        const lastIndex = ths.length - 1;
        const lastText = (ths[lastIndex].textContent || '').trim().toLowerCase();
        if (actionLabels.indexOf(lastText) !== -1) {
            actionsIndex = lastIndex;
        }
    }

    return ths.map(function (th, index) {
        const excluded = (index === actionsIndex) || (excludeSet[index] === true);
        return {
            index: index,
            th: th,
            sortable: !excluded,
            excluded: excluded
        };
    });
}

/**
 * Read the displayed (flattened) text of a body cell.
 *
 * @param {HTMLTableRowElement} row
 * @param {number} colIndex
 * @returns {string}
 */
function getCellText(row, colIndex) {
    const cell = row && row.children ? row.children[colIndex] : null;
    if (!cell) return '';
    // textContent flattens nested markup: <span class="status-active">Active</span> -> "Active",
    // <a>...url...</a> -> the url text, <select><option selected>X</option></select> -> "X".
    return (cell.textContent || '').trim();
}

/**
 * Infer the column type from displayed cell text.
 *
 * @param {string[]} values
 * @returns {'numeric'|'date'|'text'}
 */
function detectColumnType(values) {
    // Ignore empty/placeholder values so a few blanks don't force a column to text.
    const meaningful = (values || []).filter(function (v) {
        return v !== '' && v !== '-' && v !== 'N/A';
    });
    if (meaningful.length === 0) return 'text';
    // Check numeric before date so plain numbers (e.g. "2024") aren't misread as dates.
    if (meaningful.every(isNumericText)) return 'numeric';
    if (meaningful.every(isDateText)) return 'date';
    return 'text';
}

/**
 * Return true when the text represents a numeric value.
 *
 * @param {string} v
 * @returns {boolean}
 */
function isNumericText(v) {
    if (typeof v !== 'string') return false;
    // Strip currency/thousands-separators/whitespace, then a trailing duration suffix (m/s/h).
    const stripped = v.replace(/[$,\s]/g, '').replace(/(m|s|h)$/i, '');
    return stripped !== '' && !isNaN(Number(stripped));
}

/**
 * Parse a numeric value from displayed text.
 *
 * @param {string} v
 * @returns {number}
 */
function toNumber(v) {
    return parseFloat(String(v).replace(/[^0-9.\-]/g, ''));
}

/**
 * Return true when the text represents a date value.
 *
 * @param {string} v
 * @returns {boolean}
 */
function isDateText(v) {
    // A purely numeric value (e.g. "2024") stays numeric, not date.
    return !isNumericText(v) && !Number.isNaN(Date.parse(v));
}

/**
 * Parse a date (epoch ms) from displayed text.
 *
 * @param {string} v
 * @returns {number}
 */
function toDate(v) {
    return Date.parse(v);
}

/**
 * Build a type-aware comparator for the given direction.
 *
 * @param {'numeric'|'date'|'text'} type
 * @param {'asc'|'desc'} dir
 * @returns {(a:string, b:string) => number}
 */
function buildComparator(type, dir) {
    const sign = (dir === 'asc') ? 1 : -1;

    // Empty/placeholder keys sort to the end regardless of direction (treated as
    // the largest value) so blanks don't scatter through the ordering.
    function isBlank(v) {
        return v === '' || v === '-' || v === 'N/A';
    }

    return function (a, b) {
        const aBlank = isBlank(a);
        const bBlank = isBlank(b);
        if (aBlank && bBlank) return 0;
        if (aBlank) return 1;   // a sorts after b, ignoring direction
        if (bBlank) return -1;  // b sorts after a, ignoring direction

        switch (type) {
            case 'numeric':
                return sign * (toNumber(a) - toNumber(b));              // Req 2.1
            case 'date':
                return sign * (toDate(a) - toDate(b));                  // Req 2.2
            default:
                return sign * a.localeCompare(b, undefined,            // Req 2.3
                    { numeric: false, sensitivity: 'base' });
        }
    };
}

/**
 * Reorder the table's <tbody> rows by the given column, toggling direction and
 * updating indicators.
 *
 * @param {HTMLTableElement} table
 * @param {number} colIndex
 * @returns {void}
 */
function applySort(table, colIndex) {
    if (!table) return;

    const tbody = table.querySelector('tbody');
    if (!tbody) return;

    // Read/guard per-table sort state (initialized by makeSortable).
    const state = table._sortState || (table._sortState = { colIndex: null, dir: 'asc' });

    // Same column toggles direction; a new column starts ascending (Req 1.2, 1.3).
    const dir = (colIndex === state.colIndex)
        ? (state.dir === 'asc' ? 'desc' : 'asc')
        : 'asc';

    // Collect the body rows (direct children only).
    const rows = Array.from(tbody.querySelectorAll(':scope > tr'));

    // Read displayed cell text and detect the column type from those values.
    const values = rows.map(function (r) { return getCellText(r, colIndex); });
    const type = detectColumnType(values);
    const cmp = buildComparator(type, dir);

    // Decorate-sort-undecorate: keep the original index as a stable tiebreaker so
    // equal keys retain their relative order and a plain toggle reverses cleanly.
    const decorated = rows.map(function (row, i) {
        return { row: row, key: values[i], index: i };
    });
    decorated.sort(function (a, b) {
        const c = cmp(a.key, b.key);
        if (c !== 0) return c;
        return a.index - b.index;
    });

    // Reorder in place (Req 1.1).
    decorated.forEach(function (d) { tbody.appendChild(d.row); });

    // Persist state and update the indicator.
    state.colIndex = colIndex;
    state.dir = dir;
    updateIndicators(table, colIndex, dir);
}

/**
 * Clear indicators on all sortable headers and render the ▲/▼ indicator on the
 * active header.
 *
 * @param {HTMLTableElement} table
 * @param {number} activeIndex
 * @param {'asc'|'desc'} dir
 * @returns {void}
 */
function updateIndicators(table, activeIndex, dir) {
    if (!table) return;

    // Resolve headers so only sortable columns can carry an indicator; the
    // trailing Actions column (and any excluded columns) never get a glyph.
    const headers = resolveHeaders(table, table._sortOptions);

    // Locate (or lazily create) the dedicated indicator span for a header.
    // makeSortable (task 6.1) wraps each sortable label in a
    // <span class="sort-indicator"> at attach time; when that hasn't happened
    // yet we create/append one on demand so this function is self-sufficient.
    function getIndicatorSpan(th, create) {
        let span = th.querySelector('span.sort-indicator');
        if (!span && create) {
            span = th.ownerDocument.createElement('span');
            span.className = 'sort-indicator';
            th.appendChild(span);
        }
        return span;
    }

    // Clear the glyph on every sortable header's indicator span (Req 3.3).
    headers.forEach(function (h) {
        if (!h.sortable) return;
        const span = getIndicatorSpan(h.th, false);
        if (span) span.textContent = '';
    });

    // Write ▲ (asc) / ▼ (desc) into the active header's indicator span so that
    // exactly one header shows an indicator (Req 3.1, 3.2).
    const active = headers[activeIndex];
    if (active && active.sortable) {
        const span = getIndicatorSpan(active.th, true);
        span.textContent = (dir === 'asc') ? ' ▲' : ' ▼';
    }
}

/* ==========================================================================
 * Onboarding: Template Marketplace + Sandbox / Demo Mode (Req 8.2-8.6, 3.3)
 * ========================================================================== */

/**
 * Allowed sandbox deployment statuses surfaced on the Dashboard (Req 3.3).
 * Mirrors ``_ALLOWED_STATUSES`` in src/routes/sandbox_routes.py so the JS
 * render helper coerces to the same {running, stopped, failed} set.
 */
const SANDBOX_ALLOWED_STATUSES = ['running', 'stopped', 'failed'];

/**
 * Pure render helper for the dashboard sandbox payload (Req 3.3).
 *
 * Given an arbitrary array of sandbox Sample_Application objects (as returned
 * by GET /api/sandbox/status), produce, for each application, a normalized
 * entry carrying a deployment status drawn from {running, stopped, failed} and
 * its access URL. Any status not in the allowed set (including missing/unknown)
 * is coerced to 'failed', mirroring the server's ``_normalize_status``. This
 * function is intentionally DOM-free and side-effect-free so it is testable in
 * the Node harness (tests/js/onboarding-render.test.js, Property 9).
 *
 * @param {Array<Object>} apps - sandbox applications; each may carry
 *        application_id, application_name, status, access_url.
 * @returns {Array<{application_name: (string|null), status: string, access_url: (string|null)}>}
 *          one entry per input application, in input order.
 */
function renderSandboxApps(apps) {
    const list = Array.isArray(apps) ? apps : [];
    return list.map(function (app) {
        const a = (app && typeof app === 'object') ? app : {};
        const rawStatus = a.status;
        const status = SANDBOX_ALLOWED_STATUSES.indexOf(rawStatus) !== -1
            ? rawStatus
            : 'failed';
        return {
            application_name: (a.application_name != null) ? a.application_name : null,
            status: status,
            access_url: (a.access_url != null) ? a.access_url : null,
        };
    });
}

/**
 * Fetch the template catalog from GET /api/templates and render the Marketplace
 * panel with a one-click deploy control per template (Req 8.2, 8.5, 8.6).
 * Handles 401 gracefully by showing an auth-required message (Req 8.2) without
 * exposing any client path that bypasses the server-side check.
 */
async function loadTemplates() {
    const content = document.getElementById('marketplaceContent');
    if (!content) return;
    content.innerHTML = '<p>Loading templates...</p>';

    try {
        const response = await fetch('/api/templates', {
            method: 'GET',
            credentials: 'same-origin'
        });

        if (response.status === 401) {
            content.innerHTML = '<p style="color:orange;">Authentication is required. Please sign in.</p>';
            return;
        }
        if (!response.ok) {
            content.innerHTML = '<p style="color:red;">Failed to load templates.</p>';
            return;
        }

        const data = await response.json();
        const templates = (data && data.templates) || [];

        if (templates.length === 0) {
            content.innerHTML = '<p style="color:orange;">No templates available.</p>';
            return;
        }

        let html = '<table style="width:100%; border-collapse:collapse;">';
        html += '<tr style="border-bottom:1px solid #ddd;">'
            + '<th style="text-align:left; padding:5px;">Template</th>'
            + '<th style="text-align:left; padding:5px;">Type</th>'
            + '<th style="text-align:left; padding:5px;">Ports</th>'
            + '<th style="text-align:left; padding:5px;">Resources</th>'
            + '<th style="text-align:left; padding:5px;">Deploy</th></tr>';
        for (const tpl of templates) {
            const id = tpl.identifier;
            const idAttr = escapeHtml(id);
            const ports = Array.isArray(tpl.ports) ? tpl.ports.join(', ') : '';
            const resources = (tpl.memory_mb != null ? tpl.memory_mb + ' MB' : '')
                + (tpl.cpu_cores != null ? ' / ' + tpl.cpu_cores + ' CPU' : '');
            const safeId = String(id).replace(/[^a-zA-Z0-9_-]/g, '-');
            html += '<tr style="border-bottom:1px solid #eee;">';
            html += '<td style="padding:5px;">' + escapeHtml(id) + '</td>';
            html += '<td style="padding:5px;">' + escapeHtml(tpl.app_type || '') + '</td>';
            html += '<td style="padding:5px;">' + escapeHtml(ports) + '</td>';
            html += '<td style="padding:5px;">' + escapeHtml(resources) + '</td>';
            html += '<td style="padding:5px;">'
                + '<input type="text" id="tplName-' + safeId + '" placeholder="Enter an application name" style="margin-right:5px;">'
                + '<button class="btn btn-primary btn-small" onclick="deployTemplate(\'' + idAttr + '\', \'tplName-' + safeId + '\')">🚀 Deploy</button>'
                + '</td>';
            html += '</tr>';
        }
        html += '</table>';
        content.innerHTML = html;
    } catch (err) {
        content.innerHTML = '<p style="color:red;">Failed to load templates.</p>';
    }
}

/**
 * One-click deploy of a template via POST /api/templates/{id}/deploy (Req 8.2,
 * 8.3, 8.4). On success shows the deployed app and its access URL; on failure
 * shows the failure reason (rollback is handled server-side). A 401 is handled
 * gracefully with an auth-required message and no deployment is initiated
 * client-side that could bypass the server check (Req 8.2).
 *
 * @param {string} templateId - catalog identifier of the template to deploy.
 * @param {string} nameInputId - DOM id of the input holding the application name.
 */
async function deployTemplate(templateId, nameInputId) {
    const resultPanel = document.getElementById('marketplaceResultPanel');
    const resultContent = document.getElementById('marketplaceResultContent');
    const nameInput = document.getElementById(nameInputId);
    const applicationName = nameInput ? (nameInput.value || '').trim() : '';

    if (resultPanel) resultPanel.style.display = 'block';
    if (resultContent) resultContent.innerHTML = '<p>Deploying...</p>';

    if (!applicationName) {
        if (resultContent) resultContent.innerHTML = '<p style="color:red;">Enter an application name.</p>';
        return;
    }

    try {
        const response = await fetch('/api/templates/' + encodeURIComponent(templateId) + '/deploy', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ application_name: applicationName })
        });

        if (response.status === 401) {
            if (resultContent) resultContent.innerHTML = '<p style="color:orange;">Authentication is required. Please sign in.</p>';
            return;
        }

        const data = await response.json().catch(function () { return {}; });

        if (response.ok) {
            const name = escapeHtml(data.application_name || applicationName);
            const url = data.access_url || '';
            let html = '<p style="color:green;">✅ Application deployed: <strong>' + name + '</strong></p>';
            if (url) {
                html += '<p>Access URL: <a href="' + escapeHtml(url) + '" target="_blank">' + escapeHtml(url) + '</a></p>';
            }
            if (resultContent) resultContent.innerHTML = html;
        } else {
            const reason = escapeHtml((data && data.error) || 'Deployment failed');
            if (resultContent) resultContent.innerHTML = '<p style="color:red;">❌ Deployment failed: ' + reason + '</p>';
        }
    } catch (err) {
        if (resultContent) resultContent.innerHTML = '<p style="color:red;">❌ Deployment failed.</p>';
    }
}

/**
 * Trigger a sandbox lifecycle action (provision | reset | teardown) via
 * POST /api/sandbox/{action}, then refresh the status panel (Req 1.6, 2.1, 2.2).
 * A 401 is handled gracefully with an auth-required message.
 *
 * @param {('provision'|'reset'|'teardown')} action - the lifecycle action.
 */
async function sandboxAction(action) {
    const content = document.getElementById('sandboxStatusContent');
    if (content) content.innerHTML = '<p>Working...</p>';

    try {
        const response = await fetch('/api/sandbox/' + encodeURIComponent(action), {
            method: 'POST',
            credentials: 'same-origin'
        });

        if (response.status === 401) {
            if (content) content.innerHTML = '<p style="color:orange;">Authentication is required. Please sign in.</p>';
            return;
        }

        const data = await response.json().catch(function () { return {}; });
        if (!response.ok && data && data.error) {
            if (content) content.innerHTML = '<p style="color:red;">' + escapeHtml(data.error) + '</p>';
        }
    } catch (err) {
        if (content) content.innerHTML = '<p style="color:red;">Sandbox action failed.</p>';
    } finally {
        // Reflect the resulting state regardless of the action outcome.
        loadSandboxStatus();
    }
}

/**
 * Poll GET /api/sandbox/status and render the current sandbox apps with their
 * normalized status and access URL (Req 1.6, 3.3). Uses the pure
 * {@link renderSandboxApps} helper so the rendered set matches what the harness
 * test asserts. A 401 is handled gracefully.
 */
async function loadSandboxStatus() {
    const content = document.getElementById('sandboxStatusContent');
    if (!content) return;

    try {
        const response = await fetch('/api/sandbox/status', {
            method: 'GET',
            credentials: 'same-origin'
        });

        if (response.status === 401) {
            content.innerHTML = '<p style="color:orange;">Authentication is required. Please sign in.</p>';
            return;
        }
        if (!response.ok) {
            content.innerHTML = '<p style="color:red;">Failed to load sandbox status.</p>';
            return;
        }

        const data = await response.json();
        if (!data.exists) {
            content.innerHTML = '<p style="color:orange;">No sandbox environment is present.</p>';
            return;
        }

        const rows = renderSandboxApps(data.apps);
        if (rows.length === 0) {
            content.innerHTML = '<p>No sandbox applications.</p>';
            return;
        }

        let html = '<table style="width:100%; border-collapse:collapse;">';
        html += '<tr style="border-bottom:1px solid #ddd;">'
            + '<th style="text-align:left; padding:5px;">Application Name</th>'
            + '<th style="text-align:left; padding:5px;">Status</th>'
            + '<th style="text-align:left; padding:5px;">Access URL</th></tr>';
        for (const row of rows) {
            let badge;
            if (row.status === 'running') {
                badge = '<span style="background:#28a745; color:#fff; padding:2px 8px; border-radius:3px; font-size:12px;">running</span>';
            } else if (row.status === 'stopped') {
                badge = '<span style="background:#6c757d; color:#fff; padding:2px 8px; border-radius:3px; font-size:12px;">stopped</span>';
            } else {
                badge = '<span style="background:#dc3545; color:#fff; padding:2px 8px; border-radius:3px; font-size:12px;">failed</span>';
            }
            const url = row.access_url || '';
            const urlCell = url
                ? '<a href="' + escapeHtml(url) + '" target="_blank">' + escapeHtml(url) + '</a>'
                : '';
            html += '<tr style="border-bottom:1px solid #eee;">';
            html += '<td style="padding:5px;">' + escapeHtml(row.application_name || '') + '</td>';
            html += '<td style="padding:5px;">' + badge + '</td>';
            html += '<td style="padding:5px;">' + urlCell + '</td>';
            html += '</tr>';
        }
        html += '</table>';
        content.innerHTML = html;
    } catch (err) {
        content.innerHTML = '<p style="color:red;">Failed to load sandbox status.</p>';
    }
}

/*
 * Export the Sort_Helper functions for the Node/jsdom test harness. In the
 * browser `module` is undefined, so this block is skipped and the functions
 * remain plain globals loaded via <script>.
 */
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        makeSortable,
        resolveHeaders,
        getCellText,
        detectColumnType,
        isNumericText,
        toNumber,
        isDateText,
        toDate,
        buildComparator,
        applySort,
        updateIndicators,
        // Onboarding sandbox render helper (Req 3.3, tested by task 15.3)
        SANDBOX_ALLOWED_STATUSES,
        renderSandboxApps,
    };
}
