// BEFORE-UNLOAD WARNING

let blockUnload = false;

window.addEventListener("beforeunload", (event) => {
  if (blockUnload) {
    event.preventDefault();
    event.returnValue = ""; // required for Chrome
  }
});

/**
 * Injects a file into a vue component (DDM uploader).
 * @param fileInputEl - the vue element (DDM uploader) for which to trigger the upload.
 * @param file - the file to be uploaded/injected.
 */
function injectFileIntoInput(fileInputEl, file) {
  const dataTransfer = new DataTransfer();
  dataTransfer.items.add(file);
  fileInputEl.files = dataTransfer.files;

  // Dispatch change event so Vue's v-model / @change handler picks it up
  fileInputEl.dispatchEvent(new Event("change", { bubbles: true }));
}

// CSRF HELPER

/**
 * Read csrf token from Django injected input.
 *
 * @returns {*}
 */
function getCsrfToken() {
  const input = document.querySelector("[name=csrfmiddlewaretoken]");
  if (!input) throw new Error("CSRF token input not found in DOM.");
  return input.value;
}


// FILE CACHING SO DATA SURVIVES TAB/WINDOW RELOADS

// config
const CACHE_NAME = "tiktok-data-cache";
const MAX_AGE_MS = 2 * 60 * 60 * 1000; // 2 hours

/**
 * Stores file in cache including expiry metadata.
 *
 * @param file - file to be cached
 * @param maxAgeMs - maximum time in milliseconds to keep the file in the cache
 * @returns {Promise<void>}
 */
async function cacheFile(file, maxAgeMs = MAX_AGE_MS) {
  const cache = await caches.open(CACHE_NAME);
  const expiresAt = Date.now() + maxAgeMs;

  const response = new Response(file, {
    headers: {
      "Content-Type": file.type,
      "Content-Length": file.size,
      "X-Cached-At": String(Date.now()),
      "X-Expires-At": String(expiresAt),
    },
  });

  await cache.put(`/local/${file.name}`, response);
}

/**
 * Retrieves cached file.
 *
 * @param fileName - name of the file to be retrieved.
 * @returns {Promise<File|null>}
 */
async function getCachedFile(fileName) {
  const cache = await caches.open(CACHE_NAME);
  const response = await cache.match(`/local/${fileName}`);
  if (!response) return null;

  const expiresAt = Number(response.headers.get("X-Expires-At"));
  if (Number.isFinite(expiresAt) && Date.now() > expiresAt) {
    await cache.delete(`/local/${fileName}`);
    return null;
  }

  const blob = await response.blob();
  return new File([blob], fileName, { type: blob.type });
}

/**
 * Removes a specific file from the cache.
 *
 * @param fileName - name of the file to be removed.
 * @returns {Promise<void>}
 */
async function evictCachedFile(fileName) {
  const cache = await caches.open(CACHE_NAME);
  await cache.delete(`/local/${fileName}`);
}

/**
 * Removes all expired files from the cache.
 *
 * @returns {Promise<void>}
 */
async function evictExpiredCacheEntries() {
  const cache = await caches.open(CACHE_NAME);
  const requests = await cache.keys();

  for (const request of requests) {
    const response = await cache.match(request);
    const expiresAt = Number(response?.headers.get("X-Expires-At"));
    if (Number.isFinite(expiresAt) && Date.now() > expiresAt) {
      await cache.delete(request);
    }
  }
}

// MAIN DOWNLOAD + INJECT FLOW

/**
 * Main function to fetch a data takeout from TikTok's API and inject it into the DDM uploader.
 *
 * @param fileInputEl - the vue element (DDM uploader) for which to trigger the upload.
 * @param downloadUrl - the URL of the TikTok data download endpoint.
 * @returns {Promise<void>}
 */
async function fetchAndInjectTikTokData(fileInputEl, downloadUrl) {
  blockUnload = true;

  try {
    // Check cache first — survives reloads without re-downloading
    let file;
    try {
      file = await getCachedFile("tiktok_data.zip");
    } catch (error) {
      console.warn("Cache lookup failed, falling back to fresh download:", error);
      file = null;
    }

    if (!file) {
      const response = await fetch(downloadUrl, {
        method: "POST",
        headers: {
          "X-CSRFToken": getCsrfToken(),
          "Content-Type": "application/x-www-form-urlencoded",
        },
      });

      if (!response.ok) {

        if (response.status === 404) {
          const redirect_url = document.getElementById("fail-redirect-url")?.value;
          if (redirect_url) {
            window.location.href = redirect_url;
            return;
          }
        }
        throw new Error(`Server error: ${response.status} ${response.statusText}`);
      }

      const reader = response.body.getReader();
      const chunks = [];
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        chunks.push(value);
      }

      const blob = new Blob(chunks, { type: "application/zip" });
      file = new File([blob], "tiktok_data.zip", { type: "application/zip" });

      await cacheFile(file);
    }

    injectFileIntoInput(fileInputEl, file);

  } catch (error) {
    console.error("TikTok data download failed:", error);
    throw error;
  } finally {
    // Only unblock navigation once Vue component has taken over
    blockUnload = false;
  }
}

// ENTRY POINT
/**
 * Delays until the target element of the vue component (DDM uploader) is accessible on the page.
 *
 * @param selector - selector of the vue component (DDM uploader).
 * @param timeout - max time in ms to wait before rejecting.
 * @returns {Promise<unknown>}
 */
function waitForFileInput(selector, timeout = 10000) {
  return new Promise((resolve, reject) => {
    const el = document.querySelector(selector);
    if (el) return resolve(el);

    const root = document.getElementById("uapp");
    if (!root) {
      reject(new Error('Root element "#uapp" not found in DOM — cannot observe for Vue file input.'));
      return;
    }

    const observer = new MutationObserver(() => {
      const el = document.querySelector(selector);
      if (el) {
        observer.disconnect();
        resolve(el);
      }
    });

    observer.observe(root, {
      childList: true,
      subtree: true,
    });

    setTimeout(() => {
      observer.disconnect();
      reject(new Error("Timed out waiting for Vue file input to appear."));
    }, timeout);
  });
}


document.addEventListener("DOMContentLoaded", async () => {
  try {
    await evictExpiredCacheEntries();
  } catch (error) {
    console.warn("Cache eviction sweep failed (continuing anyway):", error);
  }

  const DOWNLOAD_URL = document.getElementById("tiktok-download-url")?.value;
  if (!DOWNLOAD_URL) {
    console.error("Download URL not found in DOM.");
    return;
  }

  try {
    const fileInput = await waitForFileInput("#uapp input[type='file']");
    await fetchAndInjectTikTokData(fileInput, DOWNLOAD_URL);
  } catch (error) {
    console.error("TikTok auto-download failed:", error);
  }
});

/**
 * To be called on form submission to clear the data from the cache.
 * @returns {Promise<void>}
 */
async function onFormSubmitSuccess() {
  await evictCachedFile("tiktok_data.zip");
}

// CONSOLE UTILITY: SAVE CACHED FILE TO DISK

async function saveFileToDisk(file) {
  const url = URL.createObjectURL(file);
  const a = document.createElement("a");
  a.href = url;
  a.download = file.name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/**
 * Utility function to be called from the console to download the cached file to disk.
 * @param fileName - name of the file to donwload; defaults to "tiktok_data.zip"
 * @returns {Promise<void>}
 */
async function getSaveCachedFile(fileName = "tiktok_data.zip") {
  const file = await getCachedFile(fileName);
  if (!file) {
    console.warn(`No valid (non-expired) cache entry found for "${fileName}".`);
    return;
  }
  await saveFileToDisk(file);
  console.log(`Saved "${fileName}" (${file.size} bytes) to disk.`);
}

// Expose for console access
window.getSaveCachedFile = getSaveCachedFile;
