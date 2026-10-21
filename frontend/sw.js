/* ============================================================
Service Worker —— F5 刷新加速
策略：
  1. 静态资源（js/css/图片/字体）→ 缓存优先（cache-first）
     F5 时浏览器不再发网络请求，直接从 SW 缓存返回，实现秒开
  2. index.html → 网络优先（stale-while-revalidate）
     先返回缓存版本（秒显），后台静默更新
  3. API 请求 → 不拦截，交给浏览器正常处理
  4. Swagger 文档（/api/docs, /openapi.json, /api/redoc）→ 不拦截
  5. 用户文档中心（/doc/）→ 不拦截，交给后端静态文件处理
============================================================ */

var CACHE_NAME = 'ros2-web-v4';
var STATIC_CACHE = 'ros2-web-static-v4';

// 需要缓存优先的静态资源路径前缀
var STATIC_PREFIXES = ['/css/', '/js/', '/images/', '/fonts/', '/ui/'];
var STATIC_SUFFIXES = ['.css', '.js', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.woff', '.woff2', '.ttf', '.eot'];

// 安装：预缓存核心资源
self.addEventListener('install', function(event) {
    event.waitUntil(
        caches.open(STATIC_CACHE).then(function(cache) {
            return cache.addAll([
                '/css/sj_style.css',
                '/css/onboarding.css',
                '/js/sj_script.js',
                '/js/sj_validators.js',
                '/js/onboarding.js',
                '/js/panels/data_export.js',
                '/js/panels/terminal.js',
                '/js/panels/vehicles.js',
                '/js/panels/monitor_panel.js',
                '/js/panels/traffic_batch.js',
                '/js/panels/advanced.js'
            ]).catch(function(err) {
                // 预缓存失败不阻止 SW 安装
                console.warn('[SW] 预缓存部分失败:', err);
            });
        }).then(function() {
            return self.skipWaiting();
        })
    );
});

// 激活：清理旧缓存，立即接管
self.addEventListener('activate', function(event) {
    event.waitUntil(
        caches.keys().then(function(names) {
            return Promise.all(
                names.filter(function(name) {
                    return name !== STATIC_CACHE && name !== CACHE_NAME;
                }).map(function(name) {
                    return caches.delete(name);
                })
            );
        }).then(function() {
            return self.clients.claim();
        })
    );
});

// 判断是否为静态资源
function isStaticAsset(url) {
    var path = new URL(url).pathname;
    for (var i = 0; i < STATIC_PREFIXES.length; i++) {
        if (path.startsWith(STATIC_PREFIXES[i])) return true;
    }
    for (var j = 0; j < STATIC_SUFFIXES.length; j++) {
        if (path.endsWith(STATIC_SUFFIXES[j])) return true;
    }
    return false;
}

// 判断是否为 HTML 文档
function isHtmlDocument(url) {
    var path = new URL(url).pathname;
    return path === '/' || path === '/index.html' || path.endsWith('.html');
}

// 判断是否为 API 请求
function isApiRequest(url) {
    var path = new URL(url).pathname;
    return path.startsWith('/api/') || path.startsWith('/ws');
}

// 判断是否为 Swagger/API 文档路径（不拦截，交给浏览器正常处理）
function isDocsRequest(url) {
    var path = new URL(url).pathname;
    return path === '/openapi.json' || path === '/api/docs' || path === '/api/redoc' ||
           path.startsWith('/doc/') || path === '/doc';
}

// 请求拦截
self.addEventListener('fetch', function(event) {
    var request = event.request;

    // 只处理同源 GET 请求
    if (request.method !== 'GET') return;
    var url = new URL(request.url);
    if (url.origin !== self.location.origin) return;

    // API 请求不拦截
    if (isApiRequest(request.url)) return;

    // Swagger/API 文档请求不拦截（/openapi.json, /docs, /redoc 等）
    if (isDocsRequest(request.url)) return;

    // 静态资源：缓存优先（F5 时直接返回缓存，不发网络请求）
    if (isStaticAsset(request.url)) {
        event.respondWith(
            caches.match(request).then(function(cached) {
                if (cached) {
                    // 后台静默更新缓存
                    fetch(request).then(function(resp) {
                        if (resp && resp.status === 200) {
                            var clone = resp.clone();
                            caches.open(STATIC_CACHE).then(function(cache) {
                                cache.put(request, clone);
                            });
                        }
                    }).catch(function() {});
                    return cached;
                }
                // 无缓存时从网络获取并缓存
                return fetch(request).then(function(resp) {
                    if (resp && resp.status === 200) {
                        var clone = resp.clone();
                        caches.open(STATIC_CACHE).then(function(cache) {
                            cache.put(request, clone);
                        });
                    }
                    return resp;
                });
            })
        );
        return;
    }

    // HTML 文档：stale-while-revalidate（先返回缓存，后台更新）
    if (isHtmlDocument(request.url)) {
        event.respondWith(
            caches.open(CACHE_NAME).then(function(cache) {
                return cache.match(request).then(function(cached) {
                    var fetchPromise = fetch(request).then(function(resp) {
                        if (resp && resp.status === 200) {
                            var clone = resp.clone();
                            cache.put(request, clone);
                        }
                        return resp;
                    }).catch(function() {
                        return cached;
                    });
                    // 有缓存先返回缓存（秒显），否则等网络
                    return cached || fetchPromise;
                });
            })
        );
        return;
    }
});
