// Enhanced Timesheet JavaScript
document.addEventListener('DOMContentLoaded', function() {
    const timesheetForm = document.getElementById('timesheet-form');
    const taskRows = document.querySelectorAll('.task-row');
    const addTaskBtn = document.getElementById('add-task-btn');
    const totalHoursSpan = document.getElementById('total-hours');
    const autoSaveStatus = document.getElementById('auto-save-status');
    
    let autoSaveTimer;
    let isDirty = false;
    
    // Initialize drag and drop
    initializeDragAndDrop();
    
    // Initialize auto-save
    initializeAutoSave();
    
    // Initialize validation
    initializeValidation();
    
    // Add task button
    if (addTaskBtn) {
        addTaskBtn.addEventListener('click', addNewTaskRow);
    }
    
    // Form submission
    if (timesheetForm) {
        timesheetForm.addEventListener('submit', handleFormSubmit);
    }
    
    // Real-time validation
    taskRows.forEach(row => {
        const hoursInput = row.querySelector('.hours-input');
        const descriptionInput = row.querySelector('.description-input');
        
        if (hoursInput) {
            hoursInput.addEventListener('input', validateHours);
            hoursInput.addEventListener('input', updateTotalHours);
            hoursInput.addEventListener('input', markDirty);
        }
        
        if (descriptionInput) {
            descriptionInput.addEventListener('input', validateDescription);
            descriptionInput.addEventListener('input', markDirty);
        }
    });
    
    function initializeDragAndDrop() {
        const taskContainer = document.querySelector('.task-rows-container');
        if (!taskContainer) return;
        
        new Sortable(taskContainer, {
            animation: 150,
            ghostClass: 'sortable-ghost',
            onEnd: function() {
                updateTotalHours();
                markDirty();
            }
        });
    }
    
    function initializeAutoSave() {
        // Auto-save every 30 seconds if form is dirty
        setInterval(() => {
            if (isDirty) {
                saveDraft();
            }
        }, 30000);
        
        // Auto-save on page unload
        window.addEventListener('beforeunload', function(e) {
            if (isDirty) {
                saveDraft();
                e.preventDefault();
                e.returnValue = '';
            }
        });
    }
    
    function initializeValidation() {
        // Add validation classes
        taskRows.forEach(row => {
            const hoursInput = row.querySelector('.hours-input');
            const descriptionInput = row.querySelector('.description-input');
            
            if (hoursInput) {
                hoursInput.addEventListener('blur', function() {
                    validateHours.call(this);
                });
            }
            
            if (descriptionInput) {
                descriptionInput.addEventListener('blur', function() {
                    validateDescription.call(this);
                });
            }
        });
    }
    
    function validateHours() {
        const value = parseFloat(this.value) || 0;
        const maxHours = 24;
        
        if (value < 0) {
            this.value = 0;
            showError(this, 'Hours cannot be negative');
        } else if (value > maxHours) {
            this.value = maxHours;
            showError(this, `Hours cannot exceed ${maxHours}`);
        } else {
            clearError(this);
        }
    }
    
    function validateDescription() {
        const value = this.value.trim();
        
        if (value.length < 10) {
            showError(this, 'Description must be at least 10 characters');
        } else {
            clearError(this);
        }
    }
    
    function showError(element, message) {
        element.classList.add('is-invalid');
        let errorDiv = element.parentNode.querySelector('.invalid-feedback');
        if (!errorDiv) {
            errorDiv = document.createElement('div');
            errorDiv.className = 'invalid-feedback';
            element.parentNode.appendChild(errorDiv);
        }
        errorDiv.textContent = message;
    }
    
    function clearError(element) {
        element.classList.remove('is-invalid');
        const errorDiv = element.parentNode.querySelector('.invalid-feedback');
        if (errorDiv) {
            errorDiv.remove();
        }
    }
    
    function updateTotalHours() {
        let total = 0;
        document.querySelectorAll('.hours-input').forEach(input => {
            total += parseFloat(input.value) || 0;
        });
        
        if (totalHoursSpan) {
            totalHoursSpan.textContent = total.toFixed(2);
        }
        
        // Update progress bar
        const progressBar = document.querySelector('.progress-bar');
        if (progressBar) {
            const percentage = Math.min((total / 8) * 100, 100);
            progressBar.style.width = percentage + '%';
            progressBar.setAttribute('aria-valuenow', percentage);
        }
    }
    
    function markDirty() {
        isDirty = true;
        if (autoSaveStatus) {
            autoSaveStatus.textContent = 'Unsaved changes';
            autoSaveStatus.className = 'text-warning';
        }
    }
    
    function saveDraft() {
        const formData = new FormData(timesheetForm);
        const draftData = {};
        
        // Collect form data
        for (let [key, value] of formData.entries()) {
            if (!draftData[key]) {
                draftData[key] = [];
            }
            draftData[key].push(value);
        }
        
        fetch('/timesheet/draft/save', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').getAttribute('content')
            },
            body: JSON.stringify(draftData)
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                isDirty = false;
                if (autoSaveStatus) {
                    autoSaveStatus.textContent = 'Auto-saved';
                    autoSaveStatus.className = 'text-success';
                    setTimeout(() => {
                        autoSaveStatus.textContent = '';
                        autoSaveStatus.className = '';
                    }, 2000);
                }
            }
        })
        .catch(error => {
            console.error('Auto-save failed:', error);
        });
    }
    
    function addNewTaskRow() {
        const taskContainer = document.querySelector('.task-rows-container');
        const template = document.getElementById('task-row-template');
        
        if (template && taskContainer) {
            const newRow = template.content.cloneNode(true);
            taskContainer.appendChild(newRow);
            
            // Initialize the new row
            const newTaskRow = taskContainer.lastElementChild;
            initializeTaskRow(newTaskRow);
        }
    }
    
    function initializeTaskRow(row) {
        const hoursInput = row.querySelector('.hours-input');
        const descriptionInput = row.querySelector('.description-input');
        const deleteBtn = row.querySelector('.delete-task-btn');
        
        if (hoursInput) {
            hoursInput.addEventListener('input', validateHours);
            hoursInput.addEventListener('input', updateTotalHours);
            hoursInput.addEventListener('input', markDirty);
        }
        
        if (descriptionInput) {
            descriptionInput.addEventListener('input', validateDescription);
            descriptionInput.addEventListener('input', markDirty);
        }
        
        if (deleteBtn) {
            deleteBtn.addEventListener('click', function() {
                row.remove();
                updateTotalHours();
                markDirty();
            });
        }
    }
    
    function handleFormSubmit(e) {
        // Validate form before submission
        const isValid = validateForm();
        if (!isValid) {
            e.preventDefault();
            return false;
        }
        
        // Clear dirty flag
        isDirty = false;
        
        // Show loading state
        const submitBtn = timesheetForm.querySelector('button[type="submit"]');
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Submitting...';
        }
    }
    
    function validateForm() {
        let isValid = true;
        
        // Validate total hours
        const totalHours = parseFloat(totalHoursSpan.textContent) || 0;
        if (totalHours < 1) {
            showFormError('Please log at least 1 hour of work');
            isValid = false;
        }
        
        // Validate all task rows
        document.querySelectorAll('.task-row').forEach(row => {
            const hoursInput = row.querySelector('.hours-input');
            const descriptionInput = row.querySelector('.description-input');
            
            if (hoursInput && parseFloat(hoursInput.value) > 0) {
                if (!descriptionInput.value.trim()) {
                    showFormError('Please provide descriptions for all tasks');
                    isValid = false;
                }
            }
        });
        
        return isValid;
    }
    
    function showFormError(message) {
        // Remove existing error
        const existingError = document.querySelector('.form-error');
        if (existingError) {
            existingError.remove();
        }
        
        // Add new error
        const errorDiv = document.createElement('div');
        errorDiv.className = 'alert alert-danger form-error';
        errorDiv.textContent = message;
        
        const form = document.getElementById('timesheet-form');
        form.insertBefore(errorDiv, form.firstChild);
        
        // Scroll to error
        errorDiv.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    
    // Initialize existing rows
    taskRows.forEach(row => {
        initializeTaskRow(row);
    });
    
    // Initial total calculation
    updateTotalHours();
}); 