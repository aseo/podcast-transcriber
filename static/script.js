// Global state
let episodes = [];
let activeTasks = new Map();
let refreshInterval;

// API base URL
const API_BASE = '';

// Initialize the dashboard
document.addEventListener('DOMContentLoaded', function() {
    loadEpisodes();
    setupEventListeners();
    startTaskPolling();
});

// Setup event listeners
function setupEventListeners() {
    document.getElementById('refreshBtn').addEventListener('click', loadEpisodes);
    document.getElementById('dateFilter').addEventListener('change', loadEpisodes);
    document.getElementById('statusFilter').addEventListener('change', filterEpisodes);
    document.getElementById('podcastFilter').addEventListener('change', filterEpisodes);
}

// Load episodes from API
async function loadEpisodes() {
    try {
        const days = document.getElementById('dateFilter').value;
        const response = await fetch(`${API_BASE}/episodes?days=${days}`);
        if (!response.ok) throw new Error('Failed to load episodes');
        
        episodes = await response.json();
        renderEpisodes();
        updateStats();
        updatePodcastFilter();
    } catch (error) {
        console.error('Error loading episodes:', error);
        showError('Failed to load episodes');
    }
}

// Render episodes list
function renderEpisodes() {
    const episodesList = document.getElementById('episodesList');
    const statusFilter = document.getElementById('statusFilter').value;
    const podcastFilter = document.getElementById('podcastFilter').value;
    
    // Filter episodes
    let filteredEpisodes = episodes;
    
    if (statusFilter !== 'all') {
        filteredEpisodes = filteredEpisodes.filter(episode => episode.status === statusFilter);
    }
    
    if (podcastFilter !== 'all') {
        filteredEpisodes = filteredEpisodes.filter(episode => episode.podcast_name === podcastFilter);
    }
    
    if (filteredEpisodes.length === 0) {
        episodesList.innerHTML = '<div class="loading">No episodes found</div>';
        return;
    }
    
    episodesList.innerHTML = filteredEpisodes.map(episode => createEpisodeCard(episode)).join('');
}

// Create episode card HTML
function createEpisodeCard(episode) {
    const statusClass = `status-${episode.status}`;
    const statusText = episode.status.charAt(0).toUpperCase() + episode.status.slice(1);
    
    let actionButton = '';
    if (episode.status === 'pending') {
        actionButton = `<button class="btn btn-primary" onclick="startTranscription('${episode.id}')">
            <i class="fas fa-microphone"></i> Transcribe
        </button>`;
    } else if (episode.status === 'completed') {
        actionButton = `<button class="btn btn-secondary" onclick="viewTranscript('${episode.id}')">
            <i class="fas fa-file-text"></i> View Transcript
        </button>`;
    } else if (episode.status === 'error') {
        actionButton = `<button class="btn btn-danger" onclick="startTranscription('${episode.id}')">
            <i class="fas fa-redo"></i> Retry
        </button>`;
    }
    
    const date = episode.pub_date ? new Date(episode.pub_date).toLocaleDateString() : 'Unknown date';
    
    return `
        <div class="episode-card">
            <div class="episode-header">
                <div class="episode-title">${episode.title}</div>
                <div class="episode-status ${statusClass}">${statusText}</div>
                ${actionButton}
            </div>
            <div class="episode-meta">
                <span class="episode-podcast">${episode.podcast_name}</span>
                <span class="episode-date">${date}</span>
            </div>
        </div>
    `;
}

// Update statistics
function updateStats() {
    const total = episodes.length;
    const pending = episodes.filter(e => e.status === 'pending').length;
    const completed = episodes.filter(e => e.status === 'completed').length;
    const error = episodes.filter(e => e.status === 'error').length;
    
    document.getElementById('totalEpisodes').textContent = total;
    document.getElementById('pendingEpisodes').textContent = pending;
    document.getElementById('completedEpisodes').textContent = completed;
    document.getElementById('errorEpisodes').textContent = error;
}

// Update podcast filter options
function updatePodcastFilter() {
    const podcastFilter = document.getElementById('podcastFilter');
    const podcasts = [...new Set(episodes.map(e => e.podcast_name))];
    
    // Keep the "All Podcasts" option
    podcastFilter.innerHTML = '<option value="all">All Podcasts</option>';
    
    podcasts.forEach(podcast => {
        const option = document.createElement('option');
        option.value = podcast;
        option.textContent = podcast;
        podcastFilter.appendChild(option);
    });
}

// Filter episodes
function filterEpisodes() {
    renderEpisodes();
}

// Start transcription
async function startTranscription(episodeId) {
    try {
        const button = event.target.closest('button');
        const originalText = button.innerHTML;
        
        button.disabled = true;
        button.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Starting...';
        
        const response = await fetch(`${API_BASE}/transcribe/${episodeId}`, {
            method: 'POST'
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to start transcription');
        }
        
        const result = await response.json();
        activeTasks.set(result.task_id, {
            episodeId: episodeId,
            type: 'transcribe',
            status: 'pending'
        });
        
        updateActiveTasks();
        
        // Update episode status to running
        const episode = episodes.find(e => e.id === episodeId);
        if (episode) {
            episode.status = 'running';
            renderEpisodes();
            updateStats();
        }
        
    } catch (error) {
        console.error('Error starting transcription:', error);
        showError(error.message);
        
        // Reset button
        const button = event.target.closest('button');
        button.disabled = false;
        button.innerHTML = originalText;
    }
}

// View transcript
async function viewTranscript(episodeId) {
    try {
        const response = await fetch(`${API_BASE}/transcript/${episodeId}`);
        if (!response.ok) throw new Error('Failed to load transcript');
        
        const data = await response.json();
        
        document.getElementById('modalTitle').textContent = data.episode.episode_title;
        document.getElementById('modalTranscript').textContent = data.transcript;
        document.getElementById('transcriptModal').style.display = 'block';
        
    } catch (error) {
        console.error('Error loading transcript:', error);
        showError('Failed to load transcript');
    }
}

// Close modal
function closeModal() {
    document.getElementById('transcriptModal').style.display = 'none';
}

// Start task polling
function startTaskPolling() {
    refreshInterval = setInterval(pollTasks, 2000);
}

// Poll active tasks
async function pollTasks() {
    if (activeTasks.size === 0) return;
    
    for (const [taskId, task] of activeTasks) {
        try {
            const response = await fetch(`${API_BASE}/task-status/${taskId}`);
            if (!response.ok) continue;
            
            const status = await response.json();
            task.status = status.status;
            task.message = status.message;
            
            // If task is completed or failed, remove it after a delay
            if (status.status === 'completed' || status.status === 'error') {
                setTimeout(() => {
                    activeTasks.delete(taskId);
                    updateActiveTasks();
                }, 5000);
                
                // Update episode status
                const episode = episodes.find(e => e.id === task.episodeId);
                if (episode) {
                    episode.status = status.status === 'completed' ? 'completed' : 'error';
                    renderEpisodes();
                    updateStats();
                }
            }
            
        } catch (error) {
            console.error('Error polling task:', error);
        }
    }
    
    updateActiveTasks();
}

// Update active tasks display
function updateActiveTasks() {
    const activeTasksDiv = document.getElementById('activeTasks');
    
    if (activeTasks.size === 0) {
        activeTasksDiv.innerHTML = '<div class="no-tasks">No active tasks</div>';
        return;
    }
    
    activeTasksDiv.innerHTML = Array.from(activeTasks.values()).map(task => `
        <div class="task-item">
            <div class="task-title">${task.type === 'transcribe' ? 'Transcribing Episode' : 'Unknown Task'}</div>
            <div class="task-message">${task.message || 'Processing...'}</div>
            <div class="task-progress">
                <div class="task-progress-bar" style="width: ${task.status === 'completed' ? '100%' : task.status === 'error' ? '100%' : '50%'}"></div>
            </div>
        </div>
    `).join('');
}

// Show error message
function showError(message) {
    // Simple error display - you could enhance this with a toast notification
    alert(`Error: ${message}`);
}

// Close modal when clicking outside
window.onclick = function(event) {
    const modal = document.getElementById('transcriptModal');
    if (event.target === modal) {
        closeModal();
    }
}

// Cleanup on page unload
window.addEventListener('beforeunload', function() {
    if (refreshInterval) {
        clearInterval(refreshInterval);
    }
}); 