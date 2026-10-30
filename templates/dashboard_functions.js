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
            if (linksContent) linksContent.innerHTML = '<p style="color:orange;">No opcp-serverless-* endpoints are currently running. Please start an endpoint or contact your administrator.</p>';
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

            // Populate links panel with status badges (only running endpoints from backend)
            if (linksContent) {
                let panelHtml = '<p style="font-size:12px; color:#666; margin:0 0 8px 0;"><em>Showing only running opcp-serverless-* endpoints</em></p>';
                panelHtml += '<table style="width:100%; border-collapse:collapse;">';
                panelHtml += '<tr style="border-bottom:1px solid #ddd;"><th style="text-align:left; padding:5px;">Endpoint</th><th style="text-align:left; padding:5px;">App</th><th style="text-align:left; padding:5px;">Owner</th><th style="text-align:left; padding:5px;">Status</th></tr>';
                for (const ep of endpoints) {
                    let statusBadge;
                    if (ep.status === 'AVAILABLE') {
                        statusBadge = '<span style="background:#28a745; color:#fff; padding:2px 8px; border-radius:3px; font-size:12px;">✅ AVAILABLE</span>';
                    } else if (ep.status === 'OCCUPIED') {
                        statusBadge = '<span style="background:#dc3545; color:#fff; padding:2px 8px; border-radius:3px; font-size:12px;">🔒 OCCUPIED</span>';
                    } else {
                        statusBadge = '<span style="background:#6c757d; color:#fff; padding:2px 8px; border-radius:3px; font-size:12px;">❓ UNKNOWN</span>';
                    }
                    const appName = ep.app_name || 'opcp-serverless-brik';
                    panelHtml += '<tr style="border-bottom:1px solid #eee;">';
                    panelHtml += '<td style="padding:5px;"><a href="' + ep.url + '" target="_blank" style="color:#007bff; text-decoration:none;">' + ep.url + '</a></td>';
                    panelHtml += '<td style="padding:5px;">' + appName + '</td>';
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

/* ------------------------------------------------------------------------- *
 * AppCard state -> background color resolver (Running_State highlight)        *
 *                                                                             *
 * Mirrors the state derivation and background-color assignment used by the    *
 * inline status-styling block in templates/dashboard.html (~lines 2661-2691   *
 * for derivation, ~2785-2834 for styling). Extracted here so the state->color *
 * mapping can be exercised by the Node/jsdom test harness without a full DOM. *
 *                                                                             *
 * Color mapping:                                                              *
 *   Running     -> '#d4edda' (Soft_Green)                                     *
 *   NotRunning  -> '#f8d7da' (Soft_Red)                                       *
 *   Other       -> unchanged (resolver returns '' as the "no highlight" value)*
 * ------------------------------------------------------------------------- */

/** Soft_Green background applied to Running_State AppCards. */
const RUNNING_BACKGROUND_COLOR = '#d4edda';
/** Soft_Red background applied to Not_Running_State AppCards. */
const NOT_RUNNING_BACKGROUND_COLOR = '#f8d7da';

/**
 * Resolve an AppCard's status from its raw `logs` text, mirroring the
 * derivation performed inline in templates/dashboard.html.
 *
 * The dashboard first checks for the cloned-but-not-compliant and not-cloned
 * conditions via case-insensitive log substrings, then (when the app is cloned
 * and compliant) parses the JSON emitted after a `STDOUT:` marker to read
 * `docker_compose_ps`, falling back to raw `IS_RUNNING` / `IS_NOT_RUNNING`
 * substring matching when the JSON cannot be parsed.
 *
 * @param {string} logs - Raw status/log text for the application.
 * @returns {('Running'|'NotRunning'|'Other')} The resolved status.
 */
function resolveAppCardStatus(logs) {
    const text = (logs === null || logs === undefined) ? '' : String(logs);
    const lower = text.toLowerCase();

    // Cloned-but-not-compliant and not-cloned are "Other" states: they never
    // receive the running / not-running highlight colors.
    const isClonedButNotCompliant = lower.includes('deployapp.sh not found');
    if (isClonedButNotCompliant) {
        return 'Other';
    }

    const isNotCloned = lower.includes('application not deployed') ||
                        lower.includes('clone it first');
    if (isNotCloned) {
        return 'Other';
    }

    // Cloned and compliant: determine running state. Prefer the JSON
    // `docker_compose_ps` field; fall back to raw substring matching.
    let isRunning = false;
    let isNotRunning = false;
    try {
        const lines = text.split('\n');
        const stdoutIndex = lines.findIndex(function (line) {
            return line.includes('STDOUT:');
        });
        const jsonLines = stdoutIndex >= 0 ? lines.slice(stdoutIndex + 1) : lines;
        const jsonString = jsonLines.join('\n').trim();

        const statusData = JSON.parse(jsonString);
        if (statusData && statusData.docker_compose_ps) {
            isRunning = statusData.docker_compose_ps === 'IS_RUNNING';
            isNotRunning = statusData.docker_compose_ps === 'IS_NOT_RUNNING';
        }
    } catch (e) {
        // Fallback to old text parsing when JSON is absent/malformed.
        isRunning = text.includes('IS_RUNNING');
        isNotRunning = text.includes('IS_NOT_RUNNING');
    }

    if (isRunning) {
        return 'Running';
    }
    if (isNotRunning) {
        return 'NotRunning';
    }
    return 'Other';
}

/**
 * Map a resolved AppCard status to the background color the dashboard applies.
 *
 * @param {('Running'|'NotRunning'|'Other')} status - Resolved status.
 * @returns {string} '#d4edda' for Running, '#f8d7da' for NotRunning, '' otherwise.
 */
function statusToBackgroundColor(status) {
    if (status === 'Running') {
        return RUNNING_BACKGROUND_COLOR;
    }
    if (status === 'NotRunning') {
        return NOT_RUNNING_BACKGROUND_COLOR;
    }
    // Other_State: no running/not-running highlight; leave background unchanged.
    return '';
}

/**
 * Resolve an AppCard's status from raw logs and return the background color to
 * apply. Convenience wrapper combining resolveAppCardStatus and
 * statusToBackgroundColor.
 *
 * @param {string} logs - Raw status/log text for the application.
 * @returns {string} '#d4edda' (Running), '#f8d7da' (NotRunning), or '' (Other).
 */
function resolveAppCardBackgroundColor(logs) {
    return statusToBackgroundColor(resolveAppCardStatus(logs));
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

/**
 * Normalize an Agent Control API container list into display rows. Pure: no DOM
 * and no I/O, so the jsdom harness can assert the rendered set (mirrors
 * {@link renderSandboxApps}). Produces one row per input container, in input
 * order, each carrying the required display fields with safe defaults for
 * missing/odd values (Req 5.1, 2.1, 2.2).
 *
 * @param {Array<Object>} containers - discovered containers; each may carry
 *        name, image, server_name, server_id, state, classification,
 *        confidence_score, classification_evidence.
 * @returns {Array<{name: string, image: string, server: (string|number), state: string, classification: string, confidence: number, evidence: string[]}>}
 *          one row per input container, in input order.
 */
function renderAgentRows(containers) {
    const list = Array.isArray(containers) ? containers : [];
    return list.map(function (container) {
        const c = (container && typeof container === 'object') ? container : {};
        return {
            application: c.application_name || '',
            owner: (c.owner && c.owner.username) ? c.owner.username : '',
            name: c.name || '(unnamed)',
            image: c.image || '',
            server: c.server_name || c.server_id || '',
            state: c.state || 'unknown',
            classification: c.classification || 'unclassified',
            confidence: typeof c.confidence_score === 'number' ? c.confidence_score : 0,
            evidence: Array.isArray(c.classification_evidence) ? c.classification_evidence : [],
        };
    });
}

// Marker id for the injected Evidence_Tooltip stylesheet; the styles are added
// once per document (Req 3.2).
const AGENT_EVIDENCE_TOOLTIP_STYLE_ID = 'agent-evidence-tooltip-styles';

/**
 * Inject the Evidence_Tooltip stylesheet once per document. The tooltip matches
 * the dashboard's inline-style palette (dark text on a light panel, a 1px solid
 * #ddd border, small padding, a subtle shadow, font-size 12px) and is a custom
 * styled popover rather than the native `title` attribute (Req 3.1, 3.2).
 */
function ensureAgentEvidenceTooltipStyles() {
    if (typeof document === 'undefined' || !document.head) return;
    if (document.getElementById(AGENT_EVIDENCE_TOOLTIP_STYLE_ID)) return;
    const style = document.createElement('style');
    style.id = AGENT_EVIDENCE_TOOLTIP_STYLE_ID;
    style.textContent =
        '.agent-evidence-tooltip {'
        + ' position: absolute; z-index: 1000; left: 0; top: 100%;'
        + ' max-width: 360px; padding: 6px 8px;'
        + ' background: #fff; color: #333;'
        + ' border: 1px solid #ddd; border-radius: 3px;'
        + ' box-shadow: 0 2px 6px rgba(0,0,0,0.15);'
        + ' font-size: 12px; line-height: 1.4; white-space: normal; }'
        + '.agent-evidence-tooltip .evidence-line { display: block; }';
    document.head.appendChild(style);
}

/**
 * Build an Evidence_Tooltip element for a Classification_Cell, or return null
 * when the cell carries no parseable evidence.
 *
 * The cell's `data-evidence` attribute is parsed inside a try/catch; a missing
 * attribute or a parse failure yields no tooltip (Req 2.6, and the defensive
 * JSON handling from the design). Each evidence entry is rendered as its own
 * `.evidence-line` child in array order, with its text escaped via escapeHtml
 * so classifier-supplied metacharacters render as text (Req 2.4, 2.7, 3.3).
 *
 * @param {HTMLElement} cell - the hovered `.agent-classification-cell`.
 * @returns {HTMLElement|null} a `div.agent-evidence-tooltip`, or null.
 */
function buildAgentEvidenceTooltip(cell) {
    if (!cell || typeof cell.getAttribute !== 'function') return null;
    const raw = cell.getAttribute('data-evidence');
    if (!raw) return null;
    let lines;
    try {
        lines = JSON.parse(raw);
    } catch (e) {
        // Malformed JSON yields no tooltip rather than a thrown error.
        return null;
    }
    if (!Array.isArray(lines) || lines.length === 0) return null;

    const tooltip = document.createElement('div');
    tooltip.className = 'agent-evidence-tooltip';
    // One line node per evidence entry, in array order (Req 2.4, 3.3). escapeHtml
    // neutralizes HTML metacharacters before the text reaches the DOM (Req 2.7).
    let inner = '';
    for (const line of lines) {
        inner += '<span class="evidence-line">' + escapeHtml(String(line)) + '</span>';
    }
    tooltip.innerHTML = inner;
    return tooltip;
}

/**
 * Wire a single delegated hover handler on `#agentControlContent` that shows an
 * Evidence_Tooltip while the pointer is over a `.agent-classification-cell` with
 * evidence and removes it when the pointer leaves (Req 2.3, 2.5).
 *
 * The handler is bound once per container element; a marker flag on the element
 * guards against double-binding across repeated `loadAgentControl` renders
 * (the content is full-replaced, not the container, so the listener survives).
 * Delegation uses the bubbling `mouseover`/`mouseout` events (plain `mouseenter`/
 * `mouseleave` do not bubble) and resolves the cell with `closest`, so both real
 * pointer movement and dispatched events drive the behavior.
 *
 * @param {HTMLElement} container - the `#agentControlContent` element.
 */
function wireAgentEvidenceTooltip(container) {
    if (!container || container._agentEvidenceTooltipWired) return;
    container._agentEvidenceTooltipWired = true;

    function cellFrom(target) {
        if (!target || typeof target.closest !== 'function') return null;
        const cell = target.closest('.agent-classification-cell');
        return (cell && container.contains(cell)) ? cell : null;
    }

    container.addEventListener('mouseover', function (evt) {
        const cell = cellFrom(evt.target);
        if (!cell || !cell.getAttribute('data-evidence')) return;
        // Avoid stacking tooltips if mouseover fires repeatedly within the cell.
        if (cell._agentEvidenceTooltip) return;
        const tooltip = buildAgentEvidenceTooltip(cell);
        if (!tooltip) return;
        cell._agentEvidenceTooltip = tooltip;
        cell.appendChild(tooltip);
    });

    container.addEventListener('mouseout', function (evt) {
        const cell = cellFrom(evt.target);
        if (!cell) return;
        // Ignore moves that stay within the same cell (to a descendant).
        const related = evt.relatedTarget;
        if (related && typeof cell.contains === 'function' && cell.contains(related)) return;
        const tooltip = cell._agentEvidenceTooltip;
        if (tooltip && tooltip.parentNode) {
            tooltip.parentNode.removeChild(tooltip);
        }
        cell._agentEvidenceTooltip = null;
    });
}

/**
 * Fetch the live container inventory from the Agent Control API and render the
 * "Control of Agents" table. Shows a loading indicator before the request (Req 5.4),
 * handles 401/error/network failures without breaking the refresh control (Req 5.5),
 * surfaces a per-server error banner from the payload's `errors` array (Req 4.6),
 * renders an empty-state message when there are no rows (Req 5.6), and full-replaces
 * `#agentControlContent` so a refresh wipes the prior render (Req 5.3).
 */
async function loadAgentControl() {
    const content = document.getElementById('agentControlContent');
    if (!content) return;
    // Inject the tooltip styles and wire the delegated hover handler once. The
    // container element survives the inner-HTML full-replace below, so binding it
    // here (guarded against double-binding) keeps the Evidence_Tooltip working
    // across refreshes (Req 2.3, 2.5, 3.2).
    ensureAgentEvidenceTooltipStyles();
    wireAgentEvidenceTooltip(content);
    // Loading indicator before awaiting the request (Req 5.4).
    content.innerHTML = '<p>Loading agents...</p>';

    try {
        // Use the live-scan path (?live=1): discover + classify containers across
        // every managed server on each load. The stored inventory
        // (runtime_containers) is only populated by a background scanner, so the
        // dashboard would otherwise show nothing until that scanner has run.
        const response = await fetch('/api/agent-control/containers?live=1', {
            method: 'GET',
            credentials: 'same-origin'
        });

        if (response.status === 401) {
            content.innerHTML = '<p style="color:orange;">Authentication is required. Please sign in.</p>';
            return;
        }
        if (!response.ok) {
            // Error message; the refresh control in the section header remains usable (Req 5.5).
            content.innerHTML = '<p style="color:red;">Failed to load agents.</p>';
            return;
        }

        const data = await response.json();
        const rows = renderAgentRows(data && data.containers);

        // Per-server error banner surfacing unreachable servers (Req 4.6).
        let banner = '';
        if (data && Array.isArray(data.errors) && data.errors.length) {
            const ids = data.errors.map(function (e) { return (e && e.server_id != null) ? e.server_id : '?'; });
            banner = '<p style="color:#b26a00;">⚠️ ' + escapeHtml(
                data.errors.length + ' server(s) unreachable: ' + ids.join(', ')) + '</p>';
        }

        if (rows.length === 0) {
            // Empty-state message (Req 5.6).
            content.innerHTML = banner + '<p style="color:orange;">No agents were discovered.</p>';
            return;
        }

        let html = banner + '<table style="width:100%; border-collapse:collapse;">';
        html += '<tr style="border-bottom:1px solid #ddd;">'
            + '<th style="text-align:left; padding:5px;">Application / Service</th>'
            + '<th style="text-align:left; padding:5px;">Owner</th>'
            + '<th style="text-align:left; padding:5px;">Container name</th>'
            + '<th style="text-align:left; padding:5px;">Image</th>'
            + '<th style="text-align:left; padding:5px;">Server</th>'
            + '<th style="text-align:left; padding:5px;">State</th>'
            + '<th style="text-align:left; padding:5px;">Classification</th>'
            + '<th style="text-align:left; padding:5px;">Confidence</th>'
            + '<th style="text-align:left; padding:5px;">Action</th></tr>';
        // Group rows by application so logical groups are clustered and easy to
        // read. Rows without an application name fall into a trailing
        // "(no application)" bucket. Within a group, insertion order is preserved.
        const groups = [];
        const groupIndex = {};
        for (const r of rows) {
            const key = r.application || '';
            if (!(key in groupIndex)) {
                groupIndex[key] = groups.length;
                groups.push({ application: key, rows: [] });
            }
            groups[groupIndex[key]].rows.push(r);
        }
        // Stable, readable order: named applications first (A→Z, case-insensitive),
        // the "(no application)" bucket last.
        groups.sort(function (a, b) {
            if (a.application === b.application) return 0;
            if (a.application === '') return 1;
            if (b.application === '') return -1;
            return a.application.toLowerCase().localeCompare(b.application.toLowerCase());
        });

        const COLSPAN = 9; // number of columns in the table
        for (const group of groups) {
            const hasApp = group.application !== '';
            const groupLabel = hasApp ? escapeHtml(group.application) : '(no application)';
            // Group header band: names the application once and carries the
            // application-level STOP control (enabled only for a real application).
            const groupStopBtn = hasApp
                ? '<button class="btn btn-danger btn-small" onclick="stopAgentApplication(\'' + escapeHtml(group.application) + '\')">⛔ Stop</button>'
                : '<button class="btn btn-danger btn-small" disabled title="No application name">⛔ Stop</button>';
            html += '<tr style="background:#eef3f8; border-top:2px solid #cbd6e2;">'
                + '<td colspan="' + (COLSPAN - 1) + '" style="padding:6px 5px; font-weight:600;">'
                + (hasApp ? 'Application / Service: ' : '') + groupLabel
                + ' <span style="color:#888; font-weight:400;">(' + group.rows.length + ')</span></td>'
                + '<td style="padding:6px 5px;">' + groupStopBtn + '</td>'
                + '</tr>';
            for (const r of group.rows) {
                const badge = r.classification === 'probable_agent'
                    ? '<span style="background:#28a745; color:#fff; padding:2px 8px; border-radius:3px; font-size:12px;">probable agent</span>'
                    : '<span style="background:#6c757d; color:#fff; padding:2px 8px; border-radius:3px; font-size:12px;">unclassified</span>';
                // Only cells with at least one evidence line carry data-evidence; empty
                // cells get no carrier and therefore no tooltip (Req 2.6). The JSON is
                // escaped before it reaches the attribute (Req 2.7).
                const evidenceAttr = r.evidence.length
                    ? ' data-evidence="' + escapeHtml(JSON.stringify(r.evidence)) + '"'
                    : '';
                html += '<tr style="border-bottom:1px solid #eee;">'
                    + '<td style="padding:5px 5px 5px 20px; color:#888;">↳</td>'
                    + '<td style="padding:5px;">' + (escapeHtml(r.owner) || '—') + '</td>'
                    + '<td style="padding:5px;">' + escapeHtml(r.name) + '</td>'
                    + '<td style="padding:5px;">' + escapeHtml(r.image) + '</td>'
                    + '<td style="padding:5px;">' + escapeHtml(String(r.server)) + '</td>'
                    + '<td style="padding:5px;">' + escapeHtml(r.state) + '</td>'
                    + '<td class="agent-classification-cell" style="padding:5px; position:relative;"' + evidenceAttr + '>' + badge + '</td>'
                    + '<td style="padding:5px; color:' + confidenceColor(r.confidence) + '; font-weight:600;">' + escapeHtml(confidenceText(r.confidence)) + '</td>'
                    + '<td style="padding:5px;"></td>'
                    + '</tr>';
            }
        }
        html += '</table>';
        // Full replace so a refresh wipes the prior render (Req 5.3).
        content.innerHTML = html;
    } catch (err) {
        // Thrown/network error; refresh control remains usable for retry (Req 5.5).
        content.innerHTML = '<p style="color:red;">Failed to load agents.</p>';
    }
}

/**
 * Stop a whole Compose application from the Control_View by reusing the existing
 * application-level STOP action (POST /api/deployments). Mirrors the
 * deployTemplate / sandboxAction pattern in this file.
 *
 * Guards against an empty application name (Req 3.4) so no request is sent. Sends
 * `{ action: 'STOP', application_name }` with same-origin credentials (Req 3.2).
 * On a non-ok response or a thrown error, surfaces an inline message at the top of
 * `#agentControlContent` WITHOUT refreshing, leaving the current table in place so
 * the operator keeps context (Req 3.6). On success, re-renders via loadAgentControl
 * (Req 3.5).
 *
 * @param {string} applicationName - the row's application (compose project) name.
 */
async function stopAgentApplication(applicationName) {
    if (!applicationName) return;                       // guard (Req 3.4)
    const content = document.getElementById('agentControlContent');
    try {
        const response = await fetch('/api/deployments', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'STOP', application_name: applicationName })
        });                                             // Req 3.2
        const data = await response.json().catch(function () { return {}; });
        if (!response.ok) {
            if (content) {
                content.insertAdjacentHTML('afterbegin',
                    '<p style="color:red;">⛔ Stop failed: '
                    + escapeHtml((data && data.error) || 'Unknown error') + '</p>');
            }                                           // Req 3.6
            return;
        }
        await loadAgentControl();                       // refresh (Req 3.5)
    } catch (err) {
        if (content) {
            content.insertAdjacentHTML('afterbegin',
                '<p style="color:red;">⛔ Stop failed.</p>'); // Req 3.6
        }
    }
}

// Threshold colors for the Confidence_Indicator (Req 4.1, 4.2, 4.3).
const CONFIDENCE_RED = '#dc3545';
const CONFIDENCE_ORANGE = '#fd7e14';
const CONFIDENCE_GREEN = '#28a745';

/**
 * Threshold color for a confidence score in [0,1], judged on its whole-number
 * percentage: red (<=20), orange (>20 and <51), green (>=51). Pure and exported
 * for the jsdom harness. (Req 4.1, 4.2, 4.3)
 * @param {number} score - confidence score in [0,1]
 * @returns {string} a CSS color
 */
function confidenceColor(score) {
    const pct = Math.round((typeof score === 'number' ? score : 0) * 100);
    if (pct <= 20) return CONFIDENCE_RED;
    if (pct < 51) return CONFIDENCE_ORANGE;
    return CONFIDENCE_GREEN;
}

/**
 * Render a confidence score in [0,1] as a whole-number percentage with a
 * trailing percent sign, matching the displayed banding. (Req 4.4)
 * @param {number} score - confidence score in [0,1]
 * @returns {string} e.g. "42%"
 */
function confidenceText(score) {
    const pct = Math.round((typeof score === 'number' ? score : 0) * 100);
    return pct + '%';
}

/* ======================================================================== *
 * Agent Management (ARO + ZAF) dashboard panels.
 *
 * These back the "Agent Management" navigation section. They call the
 * /api/v1/agents, /api/v1/governance and /api/v1/observability endpoints,
 * which are tenant-scoped server-side (the active tenant is resolved from the
 * session membership). Rendering is defensive: errors never break the refresh
 * control, and all interpolated values are HTML-escaped via escapeHtml.
 * ======================================================================== */

// Which AM panel ids exist; used to toggle visibility.
const AM_PANELS = ['dashboard', 'runtimes', 'instances', 'tasks', 'policies',
    'mcp', 'approvals', 'observability', 'incidents'];

/**
 * Show one Agent Management sub-panel and lazily load its content.
 * @param {string} name - panel id suffix (e.g. 'runtimes')
 */
function showAmPanel(name) {
    for (const p of AM_PANELS) {
        const el = document.getElementById('amPanel-' + p);
        if (el) el.style.display = (p === name) ? 'block' : 'none';
    }
    const loaders = {
        dashboard: loadAmDashboard,
        runtimes: loadAmRuntimes,
        instances: loadAmInstances,
        tasks: loadAmTasks,
        policies: loadAmPolicies,
        mcp: loadAmMcp,
        approvals: loadAmApprovals,
        observability: loadAmObservability,
        incidents: loadAmIncidents,
    };
    const fn = loaders[name];
    if (typeof fn === 'function') fn();
}

/** JSON GET helper for the AM panels; returns parsed body or null on failure. */
async function amGet(url) {
    try {
        const resp = await fetch(url, { method: 'GET', credentials: 'same-origin' });
        if (!resp.ok) return { __error: resp.status };
        return await resp.json();
    } catch (e) {
        return { __error: 'network' };
    }
}

/** Render a list of objects as a simple table into a container element. */
function amRenderTable(containerId, columns, rows, emptyMsg) {
    const content = document.getElementById(containerId);
    if (!content) return;
    if (rows && rows.__error) {
        content.innerHTML = '<p style="color:red;">Failed to load (' + escapeHtml(String(rows.__error)) + ').</p>';
        return;
    }
    const list = Array.isArray(rows) ? rows : [];
    if (list.length === 0) {
        content.innerHTML = '<p style="color:orange;">' + escapeHtml(emptyMsg || 'Nothing to show.') + '</p>';
        return;
    }
    let html = '<table style="width:100%; border-collapse:collapse;"><tr style="border-bottom:1px solid #ddd;">';
    for (const c of columns) html += '<th style="text-align:left; padding:5px;">' + escapeHtml(c.label) + '</th>';
    html += '</tr>';
    for (const row of list) {
        html += '<tr style="border-bottom:1px solid #eee;">';
        for (const c of columns) {
            const v = row[c.key];
            html += '<td style="padding:5px;">' + escapeHtml(v === undefined || v === null ? '' : String(
                typeof v === 'object' ? JSON.stringify(v) : v)) + '</td>';
        }
        html += '</tr>';
    }
    html += '</table>';
    content.innerHTML = html;
}

/** Entry point when the Agent Management tab opens: show the dashboard panel. */
function loadAgentManagement() {
    showAmPanel('dashboard');
}

async function loadAmDashboard() {
    const el = document.getElementById('amDashboardCards');
    if (!el) return;
    el.innerHTML = '<p>Loading...</p>';
    const [agents, metrics, approvals, incidents] = await Promise.all([
        amGet('/api/v1/agents/'),
        amGet('/api/v1/observability/metrics'),
        amGet('/api/v1/governance/approvals'),
        amGet('/api/v1/observability/incidents'),
    ]);
    const agentList = (agents && agents.agents) || [];
    const running = agentList.filter(function (a) { return a.status === 'RUNNING'; }).length;
    const failed = agentList.filter(function (a) { return a.status === 'FAILED' || a.status === 'UNHEALTHY'; }).length;
    const pending = ((approvals && approvals.approvals) || []).length;
    const incCount = ((incidents && incidents.incidents) || []).length;
    const totalEvents = (metrics && metrics.total_events) || 0;
    function card(label, value, color) {
        return '<div class="am-card" style="display:inline-block; min-width:120px; margin:6px; padding:12px 16px; '
            + 'background:#fff; border:1px solid #ddd; border-radius:6px; text-align:center;">'
            + '<div style="font-size:24px; font-weight:700; color:' + color + ';">' + escapeHtml(String(value)) + '</div>'
            + '<div style="font-size:12px; color:#666;">' + escapeHtml(label) + '</div></div>';
    }
    el.innerHTML =
        card('Total agents', agentList.length, '#333') +
        card('Running', running, '#28a745') +
        card('Failed/Unhealthy', failed, '#dc3545') +
        card('Pending approvals', pending, '#fd7e14') +
        card('Incidents', incCount, '#dc3545') +
        card('Events', totalEvents, '#007bff');
}

async function loadAmRuntimes() {
    const data = await amGet('/api/v1/agents/runtimes');
    amRenderTable('amRuntimesContent',
        [{ key: 'identifier', label: 'Identifier' }, { key: 'name', label: 'Name' },
         { key: 'version', label: 'Version' }, { key: 'supported_protocols', label: 'Protocols' },
         { key: 'status', label: 'Status' }],
        data && data.runtimes, 'No runtimes registered.');
}

async function loadAmInstances() {
    const data = await amGet('/api/v1/agents/');
    renderAgentInstancesTable('amInstancesContent', data && data.agents, 'amInstancesFeedback');
}

/*
 * Pure status -> legal-controls mapping for Agent Management lifecycle controls.
 *
 * Maps an agent's current `status` to which of the three lifecycle controls
 * (Start / Stop / Restart) are legal, derived directly from the backend
 * transition graph (src/aro/lifecycle.py, src/aro/lifecycle_service.py):
 *   - start   drives -> STARTING, legal from READY, STOPPED, FAILED
 *   - stop    drives -> STOPPING, legal from RUNNING, UNHEALTHY
 *   - restart stops-then-starts (or starts), viable from
 *             RUNNING, READY, STOPPED, FAILED, UNHEALTHY
 * Every transient/other/unknown state (REGISTERED, INSTALLING, INSTALLED,
 * CONFIGURING, STARTING, STOPPING, QUARANTINED, TERMINATED, and any value not
 * listed) enables nothing. An action presented as enabled corresponds to a
 * transition the service would accept; a disabled action corresponds to one
 * the service would reject with 409. Pure (no DOM access), plain top-level
 * declaration so inline onclick handlers resolve it in the browser, and
 * exported for the jsdom unit tests. (Req 2.5)
 *
 * @param {string} status - the agent's current lifecycle status.
 * @returns {{start: boolean, stop: boolean, restart: boolean}}
 */
function lifecycleControlState(status) {
    const start = status === 'READY' || status === 'STOPPED' || status === 'FAILED';
    const stop = status === 'RUNNING' || status === 'UNHEALTHY';
    const restart = status === 'RUNNING' || status === 'READY' || status === 'STOPPED'
        || status === 'FAILED' || status === 'UNHEALTHY';
    return { start, stop, restart };
}

/*
 * Dedicated Instances renderer for the Agent Management "Instances" panel.
 *
 * This is a SEPARATE render path from the shared amRenderTable() (which backs
 * seven other panels and emits text-only cells). Keeping the action-control
 * markup here leaves amRenderTable() provably untouched (Req 3.4) while adding
 * per-agent Start / Stop / Restart controls whose enabled/disabled state is
 * derived from lifecycleControlState(agent.status) (Req 2.1, 2.5).
 */

// The three lifecycle operations and their display labels, in render order.
const AM_LIFECYCLE_OPS = [
    { op: 'start', label: 'Start' },
    { op: 'stop', label: 'Stop' },
    { op: 'restart', label: 'Restart' },
];

/**
 * Build the <tr> HTML for the Instances table body: one row per agent with
 * ID / Identity / Name / Status cells plus an Actions cell carrying three
 * state-aware Start / Stop / Restart buttons.
 *
 * All interpolated cell and attribute values are HTML-escaped via escapeHtml.
 * The agent id used in each button's inline onclick is coerced to an integer
 * and rendered numerically, so the handler argument is never attacker-controlled
 * markup. Each button's `disabled` state comes from lifecycleControlState(status);
 * a disabled button also carries a `title` explaining why it is unavailable.
 * Pure (returns a string, no DOM access) and exported for the jsdom harness.
 * (Req 2.1, 2.5)
 *
 * @param {Array<Object>} agents - the agent objects (id, identity, name, status).
 * @returns {string} the concatenated <tr>...</tr> rows.
 */
function renderAgentInstanceRows(agents) {
    const list = Array.isArray(agents) ? agents : [];
    let html = '';
    for (const agent of list) {
        const a = agent || {};
        const status = a.status === undefined || a.status === null ? '' : String(a.status);
        const idText = a.id === undefined || a.id === null ? '' : String(a.id);
        const identityText = a.identity === undefined || a.identity === null ? '' : String(a.identity);
        const nameText = a.name === undefined || a.name === null ? '' : String(a.name);
        // Coerce the id used in the onclick to an integer rendered numerically,
        // so the inline handler argument cannot carry injected markup. A
        // non-numeric id yields 0 (no row action succeeds against a bad id).
        const idNum = parseInt(a.id, 10);
        const onclickId = Number.isFinite(idNum) ? idNum : 0;
        const state = lifecycleControlState(status);
        html += '<tr style="border-bottom:1px solid #eee;">';
        html += '<td style="padding:5px;">' + escapeHtml(idText) + '</td>';
        html += '<td style="padding:5px;">' + escapeHtml(identityText) + '</td>';
        html += '<td style="padding:5px;">' + escapeHtml(nameText) + '</td>';
        html += '<td style="padding:5px;">' + escapeHtml(status) + '</td>';
        html += '<td style="padding:5px;">';
        for (const entry of AM_LIFECYCLE_OPS) {
            const enabled = !!state[entry.op];
            const disabledAttr = enabled ? '' : ' disabled';
            const titleAttr = enabled
                ? ''
                : ' title="' + escapeHtml(entry.label + ' is not allowed while '
                    + (status || 'in this state') + '"');
            html += '<button type="button"' + disabledAttr + titleAttr
                + ' onclick="triggerAgentLifecycle(' + onclickId + ', \'' + entry.op + '\')"'
                + ' style="margin-right:4px;">' + escapeHtml(entry.label) + '</button>';
        }
        html += '</td>';
        html += '</tr>';
    }
    return html;
}

/**
 * Write the full Instances table into a container, reusing the SAME empty-state
 * text ("No agents registered.") and error-state rendering and the same
 * `__error` convention as amRenderTable (so Req 3.3 is preserved), then add a
 * dedicated per-panel feedback element (#amInstancesFeedback) that
 * triggerAgentLifecycle writes success/error messages into without disturbing
 * the table. A thin wrapper: it delegates the row markup to
 * renderAgentInstanceRows and leaves amRenderTable() untouched (Req 3.4).
 *
 * @param {string} containerId - id of the container element to render into.
 * @param {Array<Object>|{__error:*}} data - agent list, or an {__error} marker.
 * @param {string} feedbackId - id for the feedback element (e.g. 'amInstancesFeedback').
 */
function renderAgentInstancesTable(containerId, data, feedbackId) {
    const content = document.getElementById(containerId);
    if (!content) return;
    // Error state: same text and __error convention as amRenderTable (Req 3.3).
    if (data && data.__error) {
        content.innerHTML = '<p style="color:red;">Failed to load (' + escapeHtml(String(data.__error)) + ').</p>';
        return;
    }
    const list = Array.isArray(data) ? data : [];
    // Empty state: same text as amRenderTable's caller passed (Req 3.3).
    if (list.length === 0) {
        content.innerHTML = '<p style="color:orange;">' + escapeHtml('No agents registered.') + '</p>';
        return;
    }
    const fbId = feedbackId || 'amInstancesFeedback';
    let html = '<table style="width:100%; border-collapse:collapse;"><tr style="border-bottom:1px solid #ddd;">';
    html += '<th style="text-align:left; padding:5px;">' + escapeHtml('ID') + '</th>';
    html += '<th style="text-align:left; padding:5px;">' + escapeHtml('Identity') + '</th>';
    html += '<th style="text-align:left; padding:5px;">' + escapeHtml('Name') + '</th>';
    html += '<th style="text-align:left; padding:5px;">' + escapeHtml('Status') + '</th>';
    html += '<th style="text-align:left; padding:5px;">' + escapeHtml('Actions') + '</th>';
    html += '</tr>';
    html += renderAgentInstanceRows(list);
    html += '</table>';
    html += '<div id="' + escapeHtml(fbId) + '" style="margin-top:8px;"></div>';
    content.innerHTML = html;
}

/**
 * POST helper for the Instances lifecycle actions, mirroring amGet's result
 * shape. POSTs to /api/v1/agents/<agentId>/<op> with same-origin credentials,
 * parses the body defensively (a non-JSON or empty body yields {} rather than
 * throwing), and discriminates success / 409 / 404 / network error exactly as
 * amGet does: the parsed body on success, { __error: resp.status } on any
 * non-OK response (including 409 and 404), and { __error: 'network' } when the
 * request itself throws. Plain top-level declaration so it is resolvable from
 * the inline onclick handler; exported for the jsdom harness. (Req 2.2, 2.3, 2.4)
 *
 * @param {number|string} agentId - the agent's id (used in the URL path).
 * @param {string} op - the lifecycle operation: 'start', 'stop', or 'restart'.
 * @returns {Promise<Object|{__error:*}>} parsed body, or an {__error} marker.
 */
async function amPostLifecycle(agentId, op) {
    try {
        const resp = await fetch('/api/v1/agents/' + agentId + '/' + op, {
            method: 'POST',
            credentials: 'same-origin',
        });
        // Parse the body defensively: a lifecycle endpoint may answer with an
        // empty body or non-JSON content, which must not throw past the guard.
        let body = {};
        try {
            const text = await resp.text();
            body = text ? JSON.parse(text) : {};
        } catch (parseErr) {
            body = {};
        }
        if (!resp.ok) return { __error: resp.status };
        return body;
    } catch (e) {
        return { __error: 'network' };
    }
}

/**
 * Inline-onclick handler for a per-row lifecycle control. Validates the
 * operation and agent id (returning early with no request when either is
 * invalid), invokes amPostLifecycle, and surfaces the outcome in the panel's
 * dedicated feedback element (#amInstancesFeedback) with HTML-escaped text:
 * on success it refreshes the Instances table via loadAmInstances() so the
 * updated status is shown, then writes a success message; on error (409 / 404
 * / network) it writes an escaped error message WITHOUT disturbing the table
 * (the existing rows remain intact). Plain top-level async declaration so the
 * inline onclick resolves it in the browser; exported for the jsdom harness.
 * (Req 2.2, 2.3, 2.4)
 *
 * @param {number|string} agentId - the agent's id (as rendered in the onclick).
 * @param {string} op - the lifecycle operation: 'start', 'stop', or 'restart'.
 * @returns {Promise<void>}
 */
async function triggerAgentLifecycle(agentId, op) {
    // Guard: only the three known operations, and a present (non-empty) id.
    const validOp = op === 'start' || op === 'stop' || op === 'restart';
    const hasId = agentId !== undefined && agentId !== null && agentId !== '';
    if (!validOp || !hasId) return;

    const result = await amPostLifecycle(agentId, op);

    const writeFeedback = function (color, message) {
        const fb = document.getElementById('amInstancesFeedback');
        if (!fb) return;
        fb.innerHTML = '<span style="color:' + color + ';">' + escapeHtml(message) + '</span>';
    };

    if (result && result.__error) {
        // 409 / 404 / network: report the error, leave the table untouched.
        const reason = result.__error === 'network'
            ? 'network error'
            : 'error ' + String(result.__error);
        writeFeedback('red', 'Failed to ' + op + ' agent (' + reason + ').');
        return;
    }

    // Success: refresh the panel so the new status is shown, then confirm.
    await loadAmInstances();
    writeFeedback('green', 'Agent ' + op + ' succeeded.');
}

async function loadAmTasks() {
    const data = await amGet('/api/v1/agents/tasks?limit=50');
    // tasks list endpoint is per-agent; the dashboard shows recent across agents
    // via the observability events as a fallback when no direct list is wired.
    const rows = (data && data.tasks) || (data && Array.isArray(data) ? data : []);
    amRenderTable('amTasksContent',
        [{ key: 'task_ref', label: 'Task' }, { key: 'operation', label: 'Operation' },
         { key: 'status', label: 'Status' }],
        rows, 'No recent tasks.');
}

async function loadAmPolicies() {
    const data = await amGet('/api/v1/governance/policies');
    amRenderTable('amPoliciesContent',
        [{ key: 'name', label: 'Name' }, { key: 'version', label: 'Version' },
         { key: 'scope', label: 'Scope' }, { key: 'enabled', label: 'Enabled' }],
        data && data.policies, 'No policies defined.');
}

async function loadAmMcp() {
    // The MCP registry listing is surfaced through decisions/events; show the
    // governed-tool decisions as the MCP activity view.
    const data = await amGet('/api/v1/governance/decisions');
    amRenderTable('amMcpContent',
        [{ key: 'action', label: 'Action' }, { key: 'resource', label: 'Resource' },
         { key: 'decision', label: 'Decision' }, { key: 'decided_at', label: 'When' }],
        data && data.decisions, 'No governed invocations yet.');
}

async function loadAmApprovals() {
    const data = await amGet('/api/v1/governance/approvals');
    amRenderTable('amApprovalsContent',
        [{ key: 'id', label: 'ID' }, { key: 'action', label: 'Action' },
         { key: 'resource', label: 'Resource' }, { key: 'status', label: 'Status' }],
        data && data.approvals, 'No pending approvals.');
}

async function loadAmObservability() {
    const data = await amGet('/api/v1/observability/events?limit=100');
    amRenderTable('amObservabilityContent',
        [{ key: 'event_type', label: 'Event' }, { key: 'agent_id', label: 'Agent' },
         { key: 'decision', label: 'Decision' }, { key: 'severity', label: 'Severity' },
         { key: 'occurred_at', label: 'When' }],
        data && data.events, 'No events yet.');
}

async function loadAmIncidents() {
    const data = await amGet('/api/v1/observability/incidents');
    amRenderTable('amIncidentsContent',
        [{ key: 'id', label: 'ID' }, { key: 'kind', label: 'Kind' },
         { key: 'severity', label: 'Severity' }, { key: 'summary', label: 'Summary' },
         { key: 'status', label: 'Status' }],
        data && data.incidents, 'No security incidents.');
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
        // AppCard state -> color resolver (Running_State highlight)
        RUNNING_BACKGROUND_COLOR,
        NOT_RUNNING_BACKGROUND_COLOR,
        resolveAppCardStatus,
        statusToBackgroundColor,
        resolveAppCardBackgroundColor,
        // Onboarding sandbox render helper (Req 3.3, tested by task 15.3)
        SANDBOX_ALLOWED_STATUSES,
        renderSandboxApps,
        // Agent Control render helper (Req 5.1, 2.1, 2.2)
        renderAgentRows,
        // Agent Control loader (Req 5.1, 5.3, 5.4, 5.5, 5.6, 4.6, 2.3, 2.6, 2.7)
        loadAgentControl,
        // Per-row STOP handler reusing POST /api/deployments (Req 3.1, 3.2, 3.5, 3.6)
        stopAgentApplication,
        // Confidence color/text helpers (Req 4.1, 4.2, 4.3, 4.4)
        confidenceColor,
        confidenceText,
        // Evidence_Tooltip helpers (Req 2.3, 2.4, 2.5, 2.6, 3.1, 3.2, 3.3)
        ensureAgentEvidenceTooltipStyles,
        buildAgentEvidenceTooltip,
        wireAgentEvidenceTooltip,
        // Agent Management (ARO + ZAF) panel helpers (Task 18)
        AM_PANELS,
        showAmPanel,
        amRenderTable,
        loadAgentManagement,
        loadAmDashboard,
        loadAmRuntimes,
        loadAmInstances,
        // Pure status -> legal lifecycle-controls mapping (Req 2.5)
        lifecycleControlState,
        // Dedicated Instances renderer with state-aware lifecycle controls (Req 2.1, 2.5, 3.3, 3.4)
        renderAgentInstanceRows,
        renderAgentInstancesTable,
        // Lifecycle POST helper + per-row action handler (Req 2.2, 2.3, 2.4)
        amPostLifecycle,
        triggerAgentLifecycle,
        loadAmTasks,
        loadAmPolicies,
        loadAmMcp,
        loadAmApprovals,
        loadAmObservability,
        loadAmIncidents,
    };
}
