// Notifications JavaScript
document.addEventListener('DOMContentLoaded', function() {
    const notificationList = document.querySelector('.notification-list');
    const markAllReadBtn = document.querySelector('.mark-all-read-btn');
    const notificationBadge = document.querySelector('.notification-badge');
    
    // Mark notification as read
    if (notificationList) {
        notificationList.addEventListener('click', function(e) {
            if (e.target.classList.contains('mark-read-btn')) {
                const notificationId = e.target.dataset.notificationId;
                markNotificationRead(notificationId);
            }
        });
    }
    
    // Mark all notifications as read
    if (markAllReadBtn) {
        markAllReadBtn.addEventListener('click', markAllNotificationsRead);
    }
    
    // Auto-refresh notifications every 30 seconds
    setInterval(refreshNotifications, 30000);
    
    function markNotificationRead(notificationId) {
        fetch(`/notifications/mark-read/${notificationId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').getAttribute('content')
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const notificationItem = document.querySelector(`[data-notification-id="${notificationId}"]`);
                if (notificationItem) {
                    notificationItem.classList.remove('unread');
                    updateNotificationCount();
                }
            }
        })
        .catch(error => {
            console.error('Error marking notification as read:', error);
        });
    }
    
    function markAllNotificationsRead() {
        fetch('/notifications/mark-all-read', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').getAttribute('content')
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                document.querySelectorAll('.notification-item.unread').forEach(item => {
                    item.classList.remove('unread');
                });
                updateNotificationCount();
            }
        })
        .catch(error => {
            console.error('Error marking all notifications as read:', error);
        });
    }
    
    function updateNotificationCount() {
        const unreadCount = document.querySelectorAll('.notification-item.unread').length;
        if (notificationBadge) {
            if (unreadCount > 0) {
                notificationBadge.textContent = unreadCount;
                notificationBadge.style.display = 'inline';
            } else {
                notificationBadge.style.display = 'none';
            }
        }
    }
    
    function refreshNotifications() {
        fetch('/notifications/count')
        .then(response => response.json())
        .then(data => {
            if (data.count > 0 && notificationBadge) {
                notificationBadge.textContent = data.count;
                notificationBadge.style.display = 'inline';
            }
        })
        .catch(error => {
            console.error('Error refreshing notifications:', error);
        });
    }
    
    // Initialize notification count
    updateNotificationCount();
}); 