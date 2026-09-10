document.addEventListener('DOMContentLoaded', () => {
  const invalidModal = document.querySelector('.modal[data-form-invalid="true"]');
  if (invalidModal && window.bootstrap) {
    bootstrap.Modal.getOrCreateInstance(invalidModal).show();
  }

  if (window.location.hash === '#new') {
    const createModal = document.querySelector('[data-create-modal]');
    if (createModal && window.bootstrap) {
      bootstrap.Modal.getOrCreateInstance(createModal).show();
    }
  }

  document.addEventListener('keydown', (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
      event.preventDefault();
      document.querySelector('.global-search input')?.focus();
    }
  });
});
