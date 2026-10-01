const API = "/api";

const estado = {
    servidor: null,
    agrupacion: "hora",
};

// ─── Tema (claro/oscuro) ───────────────────────────────────────────────────
function aplicarTema(tema) {
    document.documentElement.setAttribute("data-theme", tema === "claro" ? "claro" : "oscuro");
    document.getElementById("logo").src =
        tema === "claro" ? "assets/img/logo-horizontal-marino.png" : "assets/img/logo-horizontal-naranja.png";
    document.getElementById("icono-tema").src =
        tema === "claro" ? "assets/img/tema-claro.png" : "assets/img/tema-oscuro.png";
}

function initTema() {
    let guardado = "oscuro";
    try {
        guardado = localStorage.getItem("tema") || "oscuro";
    } catch (e) { /* localStorage no disponible (ventana privada, etc.) */ }

    aplicarTema(guardado);

    document.getElementById("boton-tema").addEventListener("click", () => {
        const actual = document.documentElement.getAttribute("data-theme") === "claro" ? "claro" : "oscuro";
        const nuevo = actual === "claro" ? "oscuro" : "claro";
        aplicarTema(nuevo);
        try { localStorage.setItem("tema", nuevo); } catch (e) { /* ignorar */ }
        if (estado.servidor) cargarHistorico(); // recalcula colores de serie segun tema
    });
}

// ─── Utilidades ─────────────────────────────────────────────────────────────
function cssVar(nombre) {
    return getComputedStyle(document.documentElement).getPropertyValue(nombre).trim();
}

function formatearFecha(iso, agrupacion) {
    const d = new Date(iso);
    if (agrupacion === "hora") return d.toLocaleString("es-MX", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
    if (agrupacion === "dia") return d.toLocaleString("es-MX", { day: "2-digit", month: "short" });
    return d.toLocaleString("es-MX", { month: "short", year: "numeric" });
}

async function obtenerJSON(url) {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`${url} -> HTTP ${resp.status}`);
    return resp.json();
}

// ─── Servidores ─────────────────────────────────────────────────────────────
async function cargarServidores() {
    const selector = document.getElementById("selector-servidor");
    try {
        const servidores = await obtenerJSON(`${API}/servidores`);
        const activos = servidores.filter(s => s.activo);

        if (activos.length === 0) {
            selector.innerHTML = `<option value="">Sin servidores activos</option>`;
            return;
        }

        selector.innerHTML = activos.map(s => `<option value="${s.nombre}">${s.nombre}</option>`).join("");
        estado.servidor = activos[0].nombre;

        selector.addEventListener("change", () => {
            estado.servidor = selector.value;
            cargarActual();
            cargarHistorico();
        });

        cargarActual();
        cargarHistorico();
    } catch (e) {
        selector.innerHTML = `<option value="">Error al cargar servidores</option>`;
        console.error(e);
    }
}

// ─── Estado actual (tarjetas + tabla) ──────────────────────────────────────
async function cargarActual() {
    if (!estado.servidor) return;
    const contenedorTarjetas = document.getElementById("tarjetas");
    const cuerpoTabla = document.getElementById("tabla-sensores");

    try {
        const lecturas = await obtenerJSON(`${API}/servidores/${encodeURIComponent(estado.servidor)}/actual`);

        if (lecturas.length === 0) {
            contenedorTarjetas.innerHTML = `<p class="mensaje-vacio">Sin lecturas todavía para este servidor.</p>`;
            cuerpoTabla.innerHTML = "";
            return;
        }

        // Tarjeta de CPU: se muestra el core mas caliente (peor caso), no el promedio.
        const cpu = lecturas.filter(l => l.componente === "cpu");
        const gpus = lecturas.filter(l => l.componente === "gpu").sort((a, b) => a.sensor.localeCompare(b.sensor));

        const tarjetas = [];
        if (cpu.length > 0) {
            const peor = cpu.reduce((max, l) => (l.temperatura_c > max.temperatura_c ? l : max), cpu[0]);
            tarjetas.push({ titulo: "CPU (máx.)", sensor: peor.sensor, ...peor });
        }
        for (const g of gpus) {
            tarjetas.push({ titulo: g.sensor.replace("_", " "), sensor: g.sensor, ...g });
        }

        contenedorTarjetas.innerHTML = tarjetas.map(t => `
            <div class="tarjeta">
                <div class="tarjeta__titulo">${t.titulo}</div>
                <div class="tarjeta__valor">
                    <span class="punto-estado" data-estado="${t.estado || ''}"></span>${t.temperatura_c}<span class="tarjeta__unidad">°C</span>
                </div>
                <div class="tarjeta__sensor">${t.sensor}</div>
            </div>
        `).join("");

        cuerpoTabla.innerHTML = lecturas.map(l => `
            <tr>
                <td>${l.componente}</td>
                <td>${l.sensor}</td>
                <td>${l.temperatura_c} °C</td>
                <td><span class="punto-estado" data-estado="${l.estado || ''}"></span>${l.estado || '-'}</td>
                <td>${new Date(l.medido_en).toLocaleString("es-MX")}</td>
            </tr>
        `).join("");
    } catch (e) {
        contenedorTarjetas.innerHTML = `<p class="mensaje-vacio">Error al cargar el estado actual.</p>`;
        console.error(e);
    }
}

// ─── Historico (grafica) ────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll("#chips-agrupacion .chip").forEach(boton => {
        boton.addEventListener("click", () => {
            document.querySelectorAll("#chips-agrupacion .chip").forEach(b => b.setAttribute("aria-pressed", "false"));
            boton.setAttribute("aria-pressed", "true");
            estado.agrupacion = boton.dataset.agrupacion;
            cargarHistorico();
        });
    });
});

async function cargarHistorico() {
    if (!estado.servidor) return;
    const svg = document.getElementById("grafica");
    const leyenda = document.getElementById("leyenda");

    try {
        const filas = await obtenerJSON(
            `${API}/servidores/${encodeURIComponent(estado.servidor)}/historico?agrupacion=${estado.agrupacion}`
        );

        if (filas.length === 0) {
            svg.innerHTML = "";
            leyenda.innerHTML = "";
            svg.insertAdjacentHTML("afterend", "");
            document.querySelector(".grafica-contenedor").querySelector(".mensaje-vacio")?.remove();
            document.querySelector(".grafica-contenedor").insertAdjacentHTML("beforeend", `<p class="mensaje-vacio">Sin histórico todavía para este servidor.</p>`);
            return;
        }
        document.querySelector(".grafica-contenedor .mensaje-vacio")?.remove();

        const series = construirSeries(filas);
        renderGrafica(svg, series, estado.agrupacion);
        renderLeyenda(leyenda, series);
    } catch (e) {
        svg.innerHTML = "";
        console.error(e);
    }
}

// CPU: promedio de todos los sensores cpu por periodo (una sola linea).
// GPU: una linea por sensor, tal cual la entrega el backend.
function construirSeries(filas) {
    const periodos = new Set();
    const cpuPorPeriodo = new Map();
    const gpuPorSensorYPeriodo = new Map();

    for (const f of filas) {
        periodos.add(f.periodo);
        if (f.componente === "cpu") {
            if (!cpuPorPeriodo.has(f.periodo)) cpuPorPeriodo.set(f.periodo, []);
            cpuPorPeriodo.get(f.periodo).push(Number(f.temperatura_promedio));
        } else {
            if (!gpuPorSensorYPeriodo.has(f.sensor)) gpuPorSensorYPeriodo.set(f.sensor, new Map());
            gpuPorSensorYPeriodo.get(f.sensor).set(f.periodo, Number(f.temperatura_promedio));
        }
    }

    const periodosOrdenados = [...periodos].sort();
    const series = [];
    const coloresGpu = ["--serie-2", "--serie-3", "--serie-1"];

    if (cpuPorPeriodo.size > 0) {
        series.push({
            nombre: "CPU (promedio)",
            color: cssVar("--serie-1"),
            puntos: periodosOrdenados
                .filter(p => cpuPorPeriodo.has(p))
                .map(p => {
                    const valores = cpuPorPeriodo.get(p);
                    const prom = valores.reduce((a, b) => a + b, 0) / valores.length;
                    return { periodo: p, valor: Math.round(prom * 10) / 10 };
                }),
        });
    }

    let i = 0;
    for (const [sensor, mapa] of [...gpuPorSensorYPeriodo.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
        series.push({
            nombre: sensor.replace("_", " "),
            color: cssVar(coloresGpu[i % coloresGpu.length]),
            puntos: periodosOrdenados.filter(p => mapa.has(p)).map(p => ({ periodo: p, valor: mapa.get(p) })),
        });
        i++;
    }

    return series;
}

function renderLeyenda(contenedor, series) {
    contenedor.innerHTML = series.map(s => `
        <div class="leyenda__item">
            <span class="leyenda__muestra" style="background-color:${s.color}"></span>${s.nombre}
        </div>
    `).join("");
}

function renderGrafica(svg, series, agrupacion) {
    const ancho = svg.clientWidth || 1000;
    const alto = 320;
    const margen = { arriba: 16, abajo: 32, izquierda: 44, derecha: 16 };
    const anchoUtil = ancho - margen.izquierda - margen.derecha;
    const altoUtil = alto - margen.arriba - margen.abajo;

    const todosPuntos = series.flatMap(s => s.puntos);
    const periodosUnicos = [...new Set(todosPuntos.map(p => p.periodo))].sort();
    const valores = todosPuntos.map(p => p.valor);
    let yMin = Math.floor(Math.min(...valores) - 2);
    let yMax = Math.ceil(Math.max(...valores) + 2);
    if (yMin === yMax) { yMin -= 5; yMax += 5; }

    const x = (periodo) => {
        const idx = periodosUnicos.indexOf(periodo);
        return margen.izquierda + (periodosUnicos.length <= 1 ? anchoUtil / 2 : (idx / (periodosUnicos.length - 1)) * anchoUtil);
    };
    const y = (valor) => margen.arriba + altoUtil - ((valor - yMin) / (yMax - yMin)) * altoUtil;

    const colorBorde = cssVar("--borde");
    const colorMuted = cssVar("--texto-secundario");

    let svgContenido = "";

    // Gridlines horizontales + etiquetas de eje Y
    const pasosY = 4;
    for (let i = 0; i <= pasosY; i++) {
        const valor = yMin + ((yMax - yMin) / pasosY) * i;
        const yPix = y(valor);
        svgContenido += `<line x1="${margen.izquierda}" y1="${yPix}" x2="${ancho - margen.derecha}" y2="${yPix}" stroke="${colorBorde}" stroke-width="1" />`;
        svgContenido += `<text x="${margen.izquierda - 8}" y="${yPix + 4}" text-anchor="end" font-size="11" fill="${colorMuted}">${Math.round(valor)}°</text>`;
    }

    // Etiquetas de eje X (hasta 6, distribuidas)
    const maxEtiquetas = 6;
    const paso = Math.max(1, Math.ceil(periodosUnicos.length / maxEtiquetas));
    periodosUnicos.forEach((p, idx) => {
        if (idx % paso !== 0 && idx !== periodosUnicos.length - 1) return;
        svgContenido += `<text x="${x(p)}" y="${alto - 8}" text-anchor="middle" font-size="11" fill="${colorMuted}">${formatearFecha(p, agrupacion)}</text>`;
    });

    // Lineas de cada serie
    for (const s of series) {
        if (s.puntos.length === 0) continue;
        const d = s.puntos.map((p, i) => `${i === 0 ? "M" : "L"} ${x(p.periodo)} ${y(p.valor)}`).join(" ");
        svgContenido += `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" />`;
        for (const p of s.puntos) {
            svgContenido += `<circle cx="${x(p.periodo)}" cy="${y(p.valor)}" r="3" fill="${s.color}" />`;
        }
    }

    svg.setAttribute("viewBox", `0 0 ${ancho} ${alto}`);
    svg.innerHTML = svgContenido;

    activarTooltip(svg, series, periodosUnicos, x, y, margen, anchoUtil, agrupacion);
}

function activarTooltip(svg, series, periodosUnicos, x, y, margen, anchoUtil, agrupacion) {
    let tooltip = document.getElementById("tooltip-grafica");
    if (!tooltip) {
        tooltip = document.createElement("div");
        tooltip.id = "tooltip-grafica";
        tooltip.style.position = "absolute";
        tooltip.style.pointerEvents = "none";
        tooltip.style.background = cssVar("--superficie-2");
        tooltip.style.border = `1px solid ${cssVar('--borde')}`;
        tooltip.style.borderRadius = "6px";
        tooltip.style.padding = "8px 10px";
        tooltip.style.fontSize = "12px";
        tooltip.style.display = "none";
        tooltip.style.zIndex = "10";
        document.querySelector(".grafica-contenedor").style.position = "relative";
        document.querySelector(".grafica-contenedor").appendChild(tooltip);
    }

    svg.onmousemove = (ev) => {
        const rect = svg.getBoundingClientRect();
        const escalaX = svg.viewBox.baseVal.width / rect.width;
        const xPix = (ev.clientX - rect.left) * escalaX;
        const relativo = (xPix - margen.izquierda) / anchoUtil;
        const idx = Math.round(relativo * (periodosUnicos.length - 1));
        if (idx < 0 || idx >= periodosUnicos.length) { tooltip.style.display = "none"; return; }
        const periodo = periodosUnicos[idx];

        const filas = series
            .map(s => ({ nombre: s.nombre, color: s.color, punto: s.puntos.find(p => p.periodo === periodo) }))
            .filter(f => f.punto);

        if (filas.length === 0) { tooltip.style.display = "none"; return; }

        tooltip.innerHTML = `<div style="font-weight:600;margin-bottom:4px">${formatearFecha(periodo, agrupacion)}</div>` +
            filas.map(f => `<div><span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${f.color};margin-right:6px"></span>${f.nombre}: ${f.punto.valor}°C</div>`).join("");

        tooltip.style.display = "block";
        tooltip.style.left = `${ev.clientX - rect.left + 12}px`;
        tooltip.style.top = `${ev.clientY - rect.top + 12}px`;
    };
    svg.onmouseleave = () => { tooltip.style.display = "none"; };
}

// ─── Inicio ──────────────────────────────────────────────────────────────────
initTema();
cargarServidores();
setInterval(() => { cargarActual(); cargarHistorico(); }, 5 * 60 * 1000);
