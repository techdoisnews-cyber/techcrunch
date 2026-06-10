#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
📰 TECHCRUNCH TO WP AUTOMATION - Versão 1.1 (Edição Tech & AI)
Engenharia:
- Varre as páginas de categorias do TechCrunch e extrai os links das notícias recentes.
- Captura o conteúdo bruto em inglês, traduz e reescreve o artigo jornalístico em PT-BR.
- Cria prompts visuais e gera imagens destacadas exclusivas por IA (Livre de Copyright).
- Publica o post e vincula a mídia automaticamente via REST API do WordPress.
"""

import os
import sys
import json
import re
import html
import time
import base64
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from io import BytesIO

import requests
from bs4 import BeautifulSoup

# ============================================================
# CONFIGURAÇÕES GERAIS
# ============================================================

CONFIG = {
    "wordpress": {
        "site_url": "https://tech2.news", # Substitua pelo link do seu novo site
        "username": "lrodrigues",                         # Substitua pelo seu usuário do WP
        "app_password": "KrxY UlMo DBil YimH W0Ph l3i8", # Armazenada e tratada automaticamente
    },
    
    "techcrunch": {
        "categories": [
            "https://techcrunch.com/category/artificial-intelligence/",
            "https://techcrunch.com/category/apps/"
        ]
    },

    "ai": {
        "provider": "openrouter",
        "api_key": os.environ.get("OPENROUTER_API_KEY", ""),
        "model": "meta-llama/llama-3.3-70b-instruct:free",
    },

    "files": {
        "state": "state_wp_intl.json",
        "log": "automation_wp.log"
    }
}

# ============================================================
# LOGGER
# ============================================================

class Logger:
    def __init__(self, log_file: str):
        self.log_file = log_file
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    def log(self, msg: str, level: str = "INFO"):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{timestamp}] [{level}] {msg}"
        print(line)
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except: pass

    def info(self, msg: str): self.log(msg, "INFO")
    def error(self, msg: str): self.log(msg, "ERROR")
    def success(self, msg: str): self.log(msg, "SUCCESS")
    def warning(self, msg: str): self.log(msg, "WARNING")

# ============================================================
# 1. COLETOR DE LINKS E RASPADOR (TECHCRUNCH SCRAPER)
# ============================================================

class TechCrunchScraper:
    def __init__(self, logger: Logger):
        self.logger = logger
        self.headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

    def discover_links(self, category_url: str) -> List[str]:
        """Varre a listagem da categoria para achar links de posts genuínos"""
        self.logger.info(f"🔍 Varrendo categoria em busca de novidades: {category_url}")
        found_links = []
        try:
            r = requests.get(category_url, headers=self.headers, timeout=20)
            if r.status_code != 200: return []
            
            soup = BeautifulSoup(r.text, 'html.parser')
            # Localiza links dentro das tags de post do TechCrunch (padrão loops wp-block / loop arquive)
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href']
                # Filtro para pegar apenas links de posts (contendo ano/mês/dia na estrutura da URL)
                if re.search(r'/\d{4}/\d{2}/\d{2}/', href):
                    clean_url = href.split('?')[0].split('#')[0]
                    if clean_url not in found_links:
                        found_links.append(clean_url)
        except Exception as e:
            self.logger.error(f"Erro ao descobrir links na categoria: {e}")
        return found_links[:6] # Retorna as 6 mais recentes encontradas para triagem

    def extract_article(self, url: str) -> Dict:
        """Coleta o conteúdo textual bruto de dentro da notícia"""
        self.logger.info(f"🕵️ Extraindo texto completo da matéria: {url}")
        try:
            r = requests.get(url, headers=self.headers, timeout=20)
            if r.status_code != 200: return {}
            
            soup = BeautifulSoup(r.text, 'html.parser')
            
            # Captura o título H1 da matéria
            title_tag = soup.find('h1')
            title = title_tag.get_text().strip() if title_tag else ""
            
            # No TechCrunch, o conteúdo principal costuma ficar em blocos com classes de conteúdo ou artigos
            content_div = soup.find('div', class_='entry-content') or soup.find('article')
            
            paragraphs = []
            if content_div:
                paragraphs = content_div.find_all('p')
            else:
                paragraphs = soup.find_all('p')
                
            body_text = " ".join([p.get_text().strip() for p in paragraphs if len(p.get_text().strip()) > 40])
            
            return {
                "url": url,
                "title": title,
                "content": body_text
            }
        except Exception as e:
            self.logger.error(f"Falha na raspagem da notícia: {e}")
            return {}

# ============================================================
# 2. INTELIGÊNCIA ARTIFICIAL: REDAÇÃO JORNALÍSTICA E TRADUÇÃO
# ============================================================

class WPContentAI:
    def __init__(self, config: Dict, logger: Logger):
        self.cfg = config["ai"]
        self.logger = logger

    def process_and_translate(self, raw_article: Dict) -> Dict:
        api_key = self.cfg["api_key"]
        if not api_key:
            # Fallback local imediato caso a chave OpenRouter falte
            return {"title": raw_article['title'].upper(), "content": raw_article['content'][:800], "image_prompt": "Technology background"}

        prompt_jornalismo = f"""Você é o editor chefe de um portal brasileiro focado em Tecnologia e Inovação.
Sua tarefa é ler o título e a matéria em inglês extraídos do TechCrunch e reescrever um artigo jornalístico completo, profissional e formal em português (PT-BR) pronto para o nosso site.
Crie um título atraente e divida o corpo do texto em parágrafos organizados e bem desenvolvidos.

Responda seguindo exatamente este padrão estruturado de tags:
[TITULO] Escreva o título em português aqui [FIM_TITULO]
[CONTEUDO] Escreva o corpo do artigo completo em português aqui [FIM_CONTEUDO]

Matéria Bruta do TechCrunch:
Título Original: {raw_article['title']}
Texto Original: {raw_article['content']}"""

        translated_title = raw_article['title']
        translated_content = raw_article['content'][:600]

        try:
            self.logger.info("🤖 IA Etapa 1: Traduzindo e expandindo o artigo para formato web...")
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": self.cfg["model"], "messages": [{"role": "user", "content": prompt_jornalismo}], "temperature": 0.4, "max_tokens": 1200},
                timeout=45
            )
            if resp.status_code == 200:
                raw_out = resp.json()["choices"][0]["message"]["content"]
                t_match = re.search(r"\[TITULO\](.*?)\[FIM_TITULO\]", raw_out, re.DOTALL)
                c_match = re.search(r"\[CONTEUDO\](.*?)\[FIM_CONTEUDO\]", raw_out, re.DOTALL)
                if t_match: translated_title = t_match.group(1).strip()
                if c_match: translated_content = c_match.group(1).strip()
        except Exception as e:
            self.logger.warning(f"Falha na esteira de escrita da IA: {e}")

        # Geração do Prompt para a Capa (Featured Image) livre de Copyright
        prompt_imagem = f"""Com base no assunto do título: "{translated_title}", escreva um comando descritivo curto, puramente em inglês, para alimentar uma IA de desenho (Stable Diffusion).
O comando deve descrever um conceito tecnológico abstrato ou fotografia editorial limpa, realista e moderna, sem textos, letras ou marcas dentro do cenário.
Exemplo de saída: "A clean minimalist illustration of futuristic glowing neural network links, cybertech style, 8k resolution, professional." """

        image_prompt = "Futuristic clean technology abstract background, editorial, 8k resolution"
        try:
            self.logger.info("🤖 IA Etapa 2: Criando prompt artístico conceitual para a capa...")
            resp_i = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": self.cfg["model"], "messages": [{"role": "user", "content": prompt_imagem}], "temperature": 0.4, "max_tokens": 1200},
                timeout=20
            )
            if resp_i.status_code == 200:
                image_prompt = resp_i.json()["choices"][0]["message"]["content"].strip().replace('"', '')
        except Exception as e:
            self.logger.warning(f"Falha ao conceituar prompt visual: {e}")

        return {
            "title": translated_title,
            "content": translated_content,
            "image_prompt": image_prompt
        }

# ============================================================
# 3. PUBLICADOR CORE DO WORDPRESS (REST API)
# ============================================================

class WordPressPublisher:
    def __init__(self, config: Dict, logger: Logger):
        self.cfg = config["wordpress"]
        self.logger = logger
        # Limpa os espaços da senha de aplicativo para enviar uma string limpa
        clean_pass = self.cfg["app_password"].replace(" ", "")
        raw_credential = f"{self.cfg['username']}:{clean_pass}"
        self.auth_header = {"Authorization": f"Basic {base64.b64encode(raw_credential.encode()).decode()}"}

    def generate_ai_image_bytes(self, prompt_text: str) -> Optional[bytes]:
        """Baixa a imagem gerada do zero baseada no prompt descritivo da IA"""
        try:
            encoded = urllib.parse.quote(prompt_text)
            url = f"https://image.pollinations.ai/p/{encoded}?width=1200&height=675&nologo=true&enhance=true"
            self.logger.info(f"🎨 Desenhando imagem de capa inédita por IA...")
            r = requests.get(url, timeout=40)
            if r.status_code == 200 and len(r.content) > 5000:
                return r.content
        except Exception as e:
            self.logger.error(f"Erro ao baixar imagem da IA: {e}")
        return None

    def upload_media(self, img_bytes: bytes, filename: str) -> Optional[int]:
        """Faz o upload da imagem e retorna o ID de mídia do WordPress"""
        self.logger.info("📤 Enviando imagem gerada para a biblioteca do WordPress...")
        url = f"{self.cfg['site_url']}/wp-json/wp/v2/media"
        headers = {**self.auth_header, "Content-Disposition": f"attachment; filename={filename}", "Content-Type": "image/jpeg"}
        try:
            r = requests.post(url, headers=headers, data=img_bytes, timeout=35)
            if r.status_code in [200, 201]:
                media_id = r.json().get("id")
                self.logger.success(f"📸 Imagem acoplada à biblioteca! ID de mídia: {media_id}")
                return media_id
            self.logger.error(f"Erro no upload de mídia: {r.text}")
        except Exception as e:
            self.logger.error(f"Falha de conexão com a API de mídia do WP: {e}")
        return None

    def create_post(self, title: str, content: str, featured_media_id: Optional[int] = None) -> bool:
        """Publica a matéria completa estruturada no WordPress"""
        self.logger.info("🚀 Transmitindo post definitivo para o banco de dados do WordPress...")
        url = f"{self.cfg['site_url']}/wp-json/wp/v2/posts"
        
        # Converte quebras de linha em blocos HTML nativos para o editor Gutenberg
        paragraphs = content.split("\n")
        html_content = "".join([f"<p>{p.strip()}</p>" for p in paragraphs if p.strip()])
        
        payload = {
            "title": title,
            "content": html_content,
            "status": "publish" # Se quiser aprovar antes de ir ao ar, mude para "draft"
        }
        if featured_media_id:
            payload["featured_media"] = featured_media_id

        try:
            r = requests.post(url, headers=self.auth_header, json=payload, timeout=30)
            if r.status_code in [200, 201]:
                self.logger.success(f"✅ Sucesso total! Artigo publicado no site. Post ID: {r.json().get('id')}")
                return True
            self.logger.error(f"Falha ao publicar post: {r.text}")
        except Exception as e:
            self.logger.error(f"Erro de conexão com a API de posts do WP: {e}")
        return False

# ============================================================
# 4. HISTÓRICO E ORQUESTRADOR DE FLUXO
# ============================================================

class StateManager:
    def __init__(self, config: Dict):
        self.file = Path(config["files"]["state"])
        self.data = {"posted_urls": []}
        if self.file.exists():
            try: self.data = json.loads(self.file.read_text(encoding="utf-8"))
            except: pass

    def is_posted(self, url: str) -> bool: 
        return url in self.data.get("posted_urls", [])

    def mark_posted(self, url: str):
        if url not in self.data["posted_urls"]:
            self.data["posted_urls"].append(url)
            try: self.file.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
            except: pass


class TechCrunchWPBot:
    def __init__(self, config: Dict):
        self.config = config
        self.logger = Logger(config["files"]["log"])
        self.scraper = TechCrunchScraper(self.logger)
        self.ai = WPContentAI(config, self.logger)
        self.publisher = WordPressPublisher(config, self.logger)
        self.state = StateManager(config)

    def run(self):
        self.logger.info("=" * 70)
        self.logger.info("🎙️ MOTOR DE POSTS INTERNACIONAIS — AUTOMAÇÃO TECHCRUNCH")
        self.logger.info("=" * 70)

        # Varre as categorias listadas nas configurações
        all_urls = []
        for cat_url in self.config["techcrunch"]["categories"]:
            discovered = self.scraper.discover_links(cat_url)
            for url in discovered:
                if url not in all_urls:
                    all_urls.append(url)

        if not all_urls:
            self.logger.warning("Nenhuma matéria nova encontrada nas seções do TechCrunch.")
            return

        posts_executed = 0
        max_posts = self.config["schedule"]["max_posts_per_run"]

        for url in all_urls:
            if posts_executed >= max_posts: break
            if self.state.is_posted(url): continue

            # Executa o oleoduto (Pipeline) para a matéria
            raw_data = self.scraper.extract_article(url)
            if not raw_data or not raw_data.get("content"): continue

            processed = self.ai.process_and_translate(raw_data)
            
            # Etapa Gráfica por IA
            img_bytes = self.publisher.generate_ai_image_bytes(processed["image_prompt"])
            media_id = None
            if img_bytes:
                media_id = self.publisher.upload_media(img_bytes, f"capa_ai_{int(time.time())}.jpg")

            # Publicação
            success = self.publisher.create_post(processed["title"], processed["content"], media_id)
            if success:
                self.state.mark_posted(url)
                posts_executed += 1
                time.sleep(5) # Intervalo de respiro entre posts

        self.logger.info("=" * 70)


if __name__ == "__main__":
    TechCrunchWPBot(CONFIG).run()
