/**
 * Google Maps helpers for PreisMenu: shared loader + admin picker + public embed.
 * Key must be set via GOOGLE_MAPS_API_KEY (template) — never commit keys.
 */
(function (global) {
  "use strict";

  var DEFAULT_CENTER = { lat: 51.1657, lng: 10.4515 };

  function loadGoogleMapsScript(apiKey, libraries) {
    if (!apiKey) {
      return Promise.reject(new Error("Missing Google Maps API key"));
    }
    if (global.google && global.google.maps) {
      return Promise.resolve();
    }
    return new Promise(function (resolve, reject) {
      var cbName = "gmCb_" + Date.now();
      global[cbName] = function () {
        try {
          delete global[cbName];
        } catch (e) {}
        resolve();
      };
      var s = document.createElement("script");
      s.async = true;
      s.defer = true;
      s.onerror = function () {
        reject(new Error("Failed to load Google Maps JavaScript API"));
      };
      var base =
        "https://maps.googleapis.com/maps/api/js?key=" +
        encodeURIComponent(apiKey) +
        "&v=weekly&callback=" +
        encodeURIComponent(cbName);
      if (libraries) {
        base += "&libraries=" + encodeURIComponent(libraries);
      }
      s.src = base;
      document.head.appendChild(s);
    });
  }

  function initLocationPicker(opts) {
    var apiKey = opts.apiKey;
    var mapEl = document.getElementById(opts.mapId || "location-map");
    var searchEl = document.getElementById(opts.searchInputId || "location-search");
    var latEl = document.getElementById(opts.latInputId || "id_latitude");
    var lngEl = document.getElementById(opts.lngInputId || "id_longitude");
    var addrEl = document.getElementById(opts.addressInputId || "id_address");
    var placeEl = document.getElementById(opts.placeIdInputId || "id_google_place_id");
    var statusEl = document.getElementById(opts.statusId || "location-map-status");
    var loadingEl = document.getElementById(opts.loadingId || "location-map-loading");

    function setStatus(msg, isError) {
      if (statusEl) {
        statusEl.textContent = msg || "";
        statusEl.classList.toggle("text-rose-600", !!isError);
        statusEl.classList.toggle("text-slate-500", !isError);
      }
    }

    function showLoading(show) {
      if (loadingEl) loadingEl.classList.toggle("hidden", !show);
      if (mapEl) mapEl.classList.toggle("opacity-40", !!show);
    }

    function parseNum(el) {
      if (!el || !el.value) return null;
      var n = parseFloat(String(el.value).replace(",", "."));
      return isFinite(n) ? n : null;
    }

    function syncInputs(lat, lng) {
      if (latEl) latEl.value = lat != null ? String(lat) : "";
      if (lngEl) lngEl.value = lng != null ? String(lng) : "";
    }

    var initialLat = parseNum(latEl);
    var initialLng = parseNum(lngEl);
    var center =
      initialLat != null && initialLng != null
        ? { lat: initialLat, lng: initialLng }
        : DEFAULT_CENTER;

    showLoading(true);
    setStatus("");

    loadGoogleMapsScript(apiKey, "places")
      .then(function () {
        showLoading(false);
        if (mapEl) mapEl.classList.remove("hidden");
        var map = new google.maps.Map(mapEl, {
          center: center,
          zoom: initialLat != null && initialLng != null ? 16 : 6,
          mapTypeControl: false,
          streetViewControl: false,
          fullscreenControl: true,
        });

        var marker = new google.maps.Marker({
          map: map,
          position: initialLat != null && initialLng != null ? center : null,
          draggable: true,
        });

        if (initialLat == null || initialLng == null) {
          marker.setVisible(false);
        }

        var geocoder = new google.maps.Geocoder();

        function reverseGeocode(latLng) {
          try {
            geocoder.geocode({ location: latLng }, function (results, status) {
              if (status !== "OK" || !results || !results[0] || !addrEl) return;
              try {
                addrEl.value = results[0].formatted_address || addrEl.value;
              } catch (e) {}
            });
          } catch (e) {}
        }

        function placeMarker(latLng, doGeocode) {
          marker.setPosition(latLng);
          marker.setVisible(true);
          map.panTo(latLng);
          syncInputs(latLng.lat(), latLng.lng());
          if (placeEl) placeEl.value = "";
          if (doGeocode) reverseGeocode(latLng);
        }

        map.addListener("click", function (ev) {
          placeMarker(ev.latLng, true);
        });

        marker.addListener("dragend", function () {
          var p = marker.getPosition();
          syncInputs(p.lat(), p.lng());
          reverseGeocode(p);
        });

        if (searchEl && global.google.maps.places) {
          var ac = new google.maps.places.Autocomplete(searchEl, {
            fields: ["formatted_address", "geometry", "place_id", "name"],
          });
          ac.addListener("place_changed", function () {
            var place = ac.getPlace();
            if (!place.geometry || !place.geometry.location) return;
            var loc = place.geometry.location;
            map.setZoom(17);
            placeMarker(loc, false);
            if (place.formatted_address && addrEl) addrEl.value = place.formatted_address;
            if (placeEl && place.place_id) placeEl.value = place.place_id;
          });
        }

        var useBtn = document.getElementById(opts.useMarkerBtnId || "btn-use-marker");
        if (useBtn) {
          useBtn.addEventListener("click", function () {
            var p = marker.getPosition();
            if (!p) {
              setStatus("Place the marker on the map first.", true);
              return;
            }
            syncInputs(p.lat(), p.lng());
            setStatus("Coordinates updated from marker.");
          });
        }

        var clearBtn = document.getElementById(opts.clearBtnId || "btn-clear-location");
        if (clearBtn) {
          clearBtn.addEventListener("click", function () {
            marker.setVisible(false);
            syncInputs(null, null);
            if (placeEl) placeEl.value = "";
            map.setCenter(DEFAULT_CENTER);
            map.setZoom(6);
            setStatus("Location cleared. Save to apply.");
          });
        }

        var geoBtn = document.getElementById(opts.geolocateBtnId || "btn-geolocate");
        if (geoBtn && navigator.geolocation) {
          geoBtn.addEventListener("click", function () {
            navigator.geolocation.getCurrentPosition(
              function (pos) {
                var ll = {
                  lat: pos.coords.latitude,
                  lng: pos.coords.longitude,
                };
                map.setZoom(15);
                placeMarker(new google.maps.LatLng(ll.lat, ll.lng), true);
              },
              function () {
                setStatus("Could not get your location.", true);
              },
              { enableHighAccuracy: true, timeout: 10000 }
            );
          });
        }

        var copyBtn = document.getElementById(opts.copyCoordsBtnId || "btn-copy-coords");
        if (copyBtn) {
          copyBtn.addEventListener("click", function () {
            var la = latEl && latEl.value;
            var lo = lngEl && lngEl.value;
            if (!la || !lo) {
              setStatus("No coordinates to copy.", true);
              return;
            }
            var t = la + ", " + lo;
            if (navigator.clipboard && navigator.clipboard.writeText) {
              navigator.clipboard.writeText(t).then(function () {
                setStatus("Coordinates copied.");
              });
            } else {
              setStatus(t);
            }
          });
        }
      })
      .catch(function (err) {
        showLoading(false);
        setStatus(err.message || "Map could not load.", true);
      });
  }

  function initLocationEmbed(opts) {
    var apiKey = opts.apiKey;
    var el = document.getElementById(opts.mapId || "public-location-map");
    if (!el || !apiKey) return;

    var lat = parseFloat(opts.lat);
    var lng = parseFloat(opts.lng);
    if (!isFinite(lat) || !isFinite(lng)) return;

    var loading = document.getElementById(opts.loadingId || "public-location-map-loading");
    if (loading) loading.classList.remove("hidden");

    loadGoogleMapsScript(apiKey, null)
      .then(function () {
        if (loading) loading.classList.add("hidden");
        el.classList.remove("hidden");
        var map = new google.maps.Map(el, {
          center: { lat: lat, lng: lng },
          zoom: 15,
          mapTypeControl: false,
          streetViewControl: false,
        });
        new google.maps.Marker({
          map: map,
          position: { lat: lat, lng: lng },
        });
      })
      .catch(function () {
        if (loading) loading.classList.add("hidden");
        el.classList.remove("hidden");
        el.innerHTML =
          '<p class="p-4 text-sm text-slate-500">Map unavailable. Use the link below to open in Google Maps.</p>';
      });
  }

  /**
   * Load map JS only when the location block scrolls near the viewport.
   */
  function initLocationEmbedLazy(opts) {
    var root = opts.root || document.getElementById(opts.rootId || "public-location-wrap");
    if (!root) {
      initLocationEmbed(opts);
      return;
    }
    var fired = false;
    function run() {
      if (fired) return;
      fired = true;
      initLocationEmbed(opts);
    }
    if (!("IntersectionObserver" in window)) {
      run();
      return;
    }
    var obs = new IntersectionObserver(
      function (entries) {
        if (entries[0] && entries[0].isIntersecting) {
          obs.disconnect();
          run();
        }
      },
      { rootMargin: "120px", threshold: 0.01 }
    );
    obs.observe(root);
  }

  global.PreisMenuMaps = {
    loadGoogleMapsScript: loadGoogleMapsScript,
    initLocationPicker: initLocationPicker,
    initLocationEmbed: initLocationEmbed,
    initLocationEmbedLazy: initLocationEmbedLazy,
    DEFAULT_CENTER: DEFAULT_CENTER,
  };
})(typeof window !== "undefined" ? window : this);
