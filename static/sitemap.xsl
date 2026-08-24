<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform" xmlns:sm="http://www.sitemaps.org/schemas/sitemap/0.9">
  <xsl:output method="html" encoding="UTF-8" indent="yes" doctype-system="about:legacy-compat"/>
  
  <xsl:template match="/">
    <html lang="ru">
      <head>
        <meta charset="UTF-8"/>
        <meta name="viewport" content="width=device-width, initial-scale=1"/>
        <title>Карта сайта LumiBox</title>
        <style>
          * { box-sizing: border-box; }
          body { 
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, Helvetica, Arial, sans-serif; 
            line-height: 1.6; 
            max-width: 1080px; 
            margin: 0 auto; 
            padding: 1rem; 
            color: #1d1d1f; 
            background: #f5f5f7; 
          }
          h1 { 
            font-size: 1.75rem; 
            font-weight: 700; 
            margin-bottom: 0.5rem; 
            color: #e94560; 
          }
          .meta { 
            color: #6c6c82; 
            font-size: 0.875rem; 
            margin-bottom: 2rem; 
          }
          table { 
            width: 100%; 
            border-collapse: collapse; 
            background: white; 
            border-radius: 12px; 
            overflow: hidden; 
            box-shadow: 0 1px 3px rgba(16, 24, 40, 0.06), 0 6px 20px rgba(16, 24, 40, 0.06); 
          }
          th, td { 
            padding: 0.75rem 1rem; 
            text-align: left; 
            border-bottom: 1px solid #ebebed; 
            vertical-align: top; 
          }
          th { 
            background: #f5f5f7; 
            font-weight: 600; 
            font-size: 0.8125rem; 
            text-transform: uppercase; 
            letter-spacing: 0.05em; 
            color: #6c6c82; 
          }
          tr:last-child td { border-bottom: none; }
          tr:hover td { background: #fafafa; }
          .url-cell { max-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
          .url-cell a { color: #e94560; text-decoration: none; }
          .url-cell a:hover { text-decoration: underline; }
          .date-cell { font-variant-numeric: tabular-nums; color: #6c6c82; font-size: 0.875rem; }
          .freq-cell { text-transform: capitalize; color: #6c6c82; font-size: 0.875rem; }
          .priority-cell { font-variant-numeric: tabular-nums; font-weight: 600; color: #1d1d1f; }
          @media (max-width: 600px) {
            table { font-size: 0.8125rem; }
            th, td { padding: 0.5rem 0.75rem; }
            .priority-cell { display: none; }
            th:nth-child(4), td:nth-child(4) { display: none; }
          }
          footer { margin-top: 2rem; text-align: center; color: #86868b; font-size: 0.75rem; }
        </style>
      </head>
      <body>
        <h1>Карта сайта LumiBox</h1>
        <p class="meta">Всего URL: <xsl:value-of select="count(//sm:url)"/> · Обновлено: <xsl:value-of select="substring(//sm:url[1]/sm:lastmod, 1, 10)"/></p>
        <table>
          <thead>
            <tr>
              <th>URL</th>
              <th>Последнее изменение</th>
              <th>Частота</th>
              <th>Приоритет</th>
            </tr>
          </thead>
          <tbody>
            <xsl:for-each select="//sm:url">
              <tr>
                <td class="url-cell"><a href="{sm:loc}"><xsl:value-of select="sm:loc"/></a></td>
                <td class="date-cell"><xsl:if test="sm:lastmod"><xsl:value-of select="sm:lastmod"/></xsl:if></td>
                <td class="freq-cell"><xsl:if test="sm:changefreq"><xsl:value-of select="sm:changefreq"/></xsl:if></td>
                <td class="priority-cell"><xsl:if test="sm:priority"><xsl:value-of select="sm:priority"/></xsl:if></td>
              </tr>
            </xsl:for-each>
          </tbody>
        </table>
        <footer>LumiBox — каталог фильмов и сериалов · <a href="/">На главную</a></footer>
      </body>
    </html>
  </xsl:template>
</xsl:stylesheet>