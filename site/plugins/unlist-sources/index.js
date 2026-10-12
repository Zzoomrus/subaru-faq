// Локальный transformer-плагин Quartz: всё, что лежит под заданными префиксами пути
// (по умолчанию «Источники/»), получает file.data.unlisted = true. Такие страницы
// по-прежнему рендерятся в HTML и открываются по прямым ссылкам (сноски статей),
// но исчезают из поиска, графа, обозревателя, sitemap и RSS.
//
// Слаги Quartz приводит к нижнему регистру («источники/тема-16062»), а filePath
// содержит путь от каталога сборки («../wiki/Источники/Тема 16062.md»), поэтому
// сравниваем без учёта регистра и ищем префикс как сегмент пути.
const norm = (s) => String(s ?? "").replace(/\\/g, "/").toLowerCase()

const rehypeUnlistSources = (prefixes) => {
  const pats = prefixes.map((p) => norm(p).replace(/\/+$/, "") + "/")
  return () => (_tree, file) => {
    const fp = norm(file.data?.filePath)
    const slug = norm(file.data?.slug) + "/"
    for (const p of pats) {
      if (slug.startsWith(p) || fp.startsWith(p) || fp.includes("/" + p)) {
        file.data.unlisted = true
        return
      }
    }
  }
}

const UnlistSources = (userOpts) => {
  const prefixes = userOpts?.prefixes ?? ["Источники/"]
  return {
    name: "UnlistSources",
    htmlPlugins() {
      return [rehypeUnlistSources(prefixes)]
    },
  }
}

export { UnlistSources }
