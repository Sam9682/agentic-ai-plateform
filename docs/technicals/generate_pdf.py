#!/usr/bin/env python3
"""Generate a marketing-style PDF from the platform overview content.

Targeted at non-technical decision makers to explain the benefits
of using the platform for application deployment and management.

The platform display name and output filename are derived from PLTF_NAME in
conf/deploy.ini (falling back to the canonical default) so the generated
document carries the configured platform identity rather than a hardcoded one.

Usage:
    python3 docs/generate_pdf.py

Requirements:
    pip install weasyprint
"""

from weasyprint import HTML
import os
import re


def get_platform_name():
    """Read PLTF_NAME from conf/deploy.ini, falling back to the canonical
    default. Mirrors the tiny parser used across the platform's shell/py glue."""
    try:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        config_path = os.path.join(base_dir, 'conf', 'deploy.ini')
        with open(config_path, 'r') as f:
            for line in f:
                if line.strip().startswith('PLTF_NAME'):
                    return line.split('=', 1)[1].strip().strip("'\"")
    except Exception:
        pass
    return 'agentic-ai-plateform_AI_SharedGPU_Docker_Serverless'


PLATFORM_NAME = get_platform_name()
PLATFORM_SLUG = re.sub(r'[^A-Za-z0-9._-]+', '-', PLATFORM_NAME).strip('-') or 'platform'

# The platform display name is injected by replacing the @@PLATFORM_NAME@@
# sentinel below. A sentinel (rather than str.format) avoids having to escape
# the many literal braces in the embedded CSS.
html_template = """
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<style>
@page {
    size: A4;
    margin: 0;
}

body {
    font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
    margin: 0;
    padding: 0;
    color: #2c3e50;
    line-height: 1.6;
}

/* Cover Page */
.cover {
    height: 297mm;
    background: linear-gradient(135deg, #0a1628 0%, #1a2744 50%, #0f3460 100%);
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    text-align: center;
    color: white;
    padding: 60px;
    page-break-after: always;
}

.cover h1 {
    font-size: 48px;
    font-weight: 700;
    margin-bottom: 20px;
    letter-spacing: -0.5px;
}

.cover .subtitle {
    font-size: 22px;
    font-weight: 300;
    opacity: 0.9;
    margin-bottom: 40px;
}

.cover .tagline {
    font-size: 16px;
    font-weight: 300;
    opacity: 0.7;
    border-top: 1px solid rgba(255,255,255,0.3);
    padding-top: 30px;
    margin-top: 40px;
    max-width: 500px;
}

.cover .brand {
    font-size: 18px;
    font-weight: 600;
    letter-spacing: 2px;
    text-transform: uppercase;
    margin-top: 60px;
    opacity: 0.8;
}

.cover .version {
    font-size: 12px;
    opacity: 0.5;
    margin-top: 10px;
}

/* Content Pages */
.page {
    padding: 50px 60px;
    page-break-after: always;
}

.page:last-child {
    page-break-after: avoid;
}

h2 {
    font-size: 28px;
    color: #0f3460;
    font-weight: 700;
    margin-bottom: 25px;
    padding-bottom: 10px;
    border-bottom: 3px solid #3498db;
}

h3 {
    font-size: 20px;
    color: #16213e;
    font-weight: 600;
    margin-top: 30px;
    margin-bottom: 15px;
}

p {
    font-size: 14px;
    margin-bottom: 15px;
    color: #444;
}

.intro-text {
    font-size: 16px;
    color: #555;
    line-height: 1.8;
    margin-bottom: 30px;
}

/* Feature Cards */
.features {
    display: flex;
    flex-wrap: wrap;
    gap: 20px;
    margin: 30px 0;
}

.feature-card {
    background: #f8f9fa;
    border-radius: 12px;
    padding: 25px;
    width: 45%;
    border-left: 4px solid #3498db;
}

.feature-card h4 {
    font-size: 16px;
    color: #0f3460;
    margin: 0 0 10px 0;
    font-weight: 600;
}

.feature-card p {
    font-size: 13px;
    color: #666;
    margin: 0;
}

/* Benefits List */
.benefits {
    list-style: none;
    padding: 0;
}

.benefits li {
    font-size: 15px;
    padding: 12px 0 12px 35px;
    position: relative;
    border-bottom: 1px solid #eee;
}

.benefits li::before {
    content: "✓";
    position: absolute;
    left: 0;
    color: #3498db;
    font-weight: 700;
    font-size: 18px;
}

/* Timeline / Steps */
.timeline {
    margin: 30px 0;
}

.timeline-item {
    display: flex;
    align-items: flex-start;
    margin-bottom: 20px;
}

.timeline-badge {
    background: #0f3460;
    color: white;
    width: 40px;
    height: 40px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
    font-size: 14px;
    margin-right: 20px;
    flex-shrink: 0;
}

.timeline-content {
    flex: 1;
}

.timeline-content h4 {
    margin: 0 0 5px 0;
    font-size: 16px;
    color: #16213e;
}

.timeline-content p {
    margin: 0;
    font-size: 13px;
    color: #666;
}

/* Use Case Cards */
.usecase-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 15px;
    margin: 25px 0;
}

.usecase-card {
    background: linear-gradient(135deg, #f8f9fa, #e9ecef);
    border-radius: 10px;
    padding: 20px;
    width: 44%;
}

.usecase-card .usecase-icon {
    font-size: 28px;
    margin-bottom: 10px;
}

.usecase-card h4 {
    font-size: 15px;
    color: #0f3460;
    margin: 8px 0;
}

.usecase-card p {
    font-size: 12px;
    color: #666;
    margin: 0;
}

/* Interface Table */
.interface-table {
    width: 100%;
    border-collapse: collapse;
    margin: 25px 0;
}

.interface-table th {
    background: #0f3460;
    color: white;
    padding: 12px 15px;
    text-align: left;
    font-size: 13px;
}

.interface-table td {
    padding: 12px 15px;
    border-bottom: 1px solid #eee;
    font-size: 13px;
    color: #444;
}

.interface-table tr:nth-child(even) {
    background: #f8f9fa;
}

/* CTA Section */
.cta {
    background: linear-gradient(135deg, #0f3460, #16213e);
    border-radius: 15px;
    padding: 40px;
    text-align: center;
    color: white;
    margin-top: 40px;
}

.cta h3 {
    color: white;
    font-size: 24px;
    margin: 0 0 15px 0;
}

.cta p {
    color: rgba(255,255,255,0.8);
    font-size: 15px;
    margin-bottom: 25px;
}

.cta .contact {
    font-size: 18px;
    font-weight: 600;
    color: #3498db;
}

/* Highlight Box */
.highlight-box {
    background: linear-gradient(135deg, #eaf4fd, #d6eaf8);
    border: 1px solid #3498db;
    border-radius: 12px;
    padding: 25px;
    margin: 25px 0;
}

.highlight-box h4 {
    color: #0f3460;
    margin: 0 0 10px 0;
    font-size: 16px;
}

/* Architecture Diagram */
.architecture {
    background: #f8f9fa;
    border-radius: 12px;
    padding: 30px;
    margin: 25px 0;
    text-align: center;
    font-family: 'Courier New', monospace;
    font-size: 12px;
    line-height: 1.4;
    white-space: pre;
    color: #333;
}

/* Stats row */
.stats-row {
    display: flex;
    gap: 20px;
    margin: 30px 0;
}

.stat-box {
    flex: 1;
    background: linear-gradient(135deg, #0f3460, #1a2744);
    border-radius: 12px;
    padding: 25px;
    text-align: center;
    color: white;
}

.stat-box .stat-number {
    font-size: 32px;
    font-weight: 700;
    color: #3498db;
    margin-bottom: 5px;
}

.stat-box .stat-label {
    font-size: 12px;
    opacity: 0.8;
    text-transform: uppercase;
    letter-spacing: 1px;
}

/* Footer */
.footer {
    text-align: center;
    padding: 20px;
    font-size: 11px;
    color: #999;
    margin-top: 40px;
}
</style>
</head>
<body>

<!-- COVER PAGE -->
<div class="cover">
    <h1>@@PLATFORM_NAME@@</h1>
    <div class="subtitle">Votre plateforme centralisée de déploiement<br>et de gestion d'applications</div>
    <div class="tagline">Déployez, supervisez et faites évoluer vos applications web<br>en toute simplicité, grâce à une interface unique<br>et des processus entièrement automatisés.</div>
    <div class="brand">PSMC OVHcloud</div>
    <div class="version">agentic-ai-plateform.com</div>
</div>

<!-- PAGE 2: VALUE PROPOSITION -->
<div class="page">
    <h2>Simplifiez votre infrastructure applicative</h2>
    <p class="intro-text">
        @@PLATFORM_NAME@@ est une plateforme tout-en-un qui vous libère des complexités
        de l'hébergement et du déploiement. Que vous soyez une startup, une PME ou une équipe
        en croissance, la plateforme s'adapte à vos besoins et vous permet de vous concentrer
        sur ce qui compte : votre métier.
    </p>

    <h3>Vos bénéfices immédiats</h3>
    <ul class="benefits">
        <li>Déploiement automatisé depuis un dépôt Git en une seule action</li>
        <li>Supervision en temps réel de tous vos services depuis un tableau de bord unique</li>
        <li>Sécurité intégrée : WAF, authentification 2FA, chiffrement SSL</li>
        <li>Scalabilité horizontale avec orchestration automatique des répliques</li>
        <li>Accès GPU partagé pour vos charges de travail IA sans investissement matériel</li>
        <li>Sauvegardes automatiques avec synchronisation cloud S3</li>
    </ul>

    <div class="highlight-box">
        <h4>💡 Aucune expertise DevOps requise</h4>
        <p style="margin:0; font-size: 14px; color: #555;">
            Le tableau de bord web vous guide étape par étape. Votre équipe peut déployer
            et superviser des applications en quelques minutes, sans toucher à la ligne de commande.
        </p>
    </div>
</div>

<!-- PAGE 3: KEY FEATURES -->
<div class="page">
    <h2>Des fonctionnalités pensées pour votre productivité</h2>

    <div class="timeline">
        <div class="timeline-item">
            <div class="timeline-badge">1</div>
            <div class="timeline-content">
                <h4>Déploiement en Un Clic</h4>
                <p>Connectez votre dépôt Git, la plateforme clone, construit et lance votre application automatiquement. Mises à jour sans interruption de service.</p>
            </div>
        </div>
        <div class="timeline-item">
            <div class="timeline-badge">2</div>
            <div class="timeline-content">
                <h4>Orchestration Intelligente</h4>
                <p>Créez plusieurs répliques de vos services. L'orchestrateur surveille la santé et relance automatiquement les instances défaillantes.</p>
            </div>
        </div>
        <div class="timeline-item">
            <div class="timeline-badge">3</div>
            <div class="timeline-content">
                <h4>GPU Partagé (NVIDIA MIG)</h4>
                <p>Accédez à la puissance GPU sans matériel dédié. Le partitionnement MIG isole les ressources entre utilisateurs pour une sécurité maximale.</p>
            </div>
        </div>
        <div class="timeline-item">
            <div class="timeline-badge">4</div>
            <div class="timeline-content">
                <h4>Exécution Serverless</h4>
                <p>Soumettez des tâches Docker à la demande : traitements batch, pipelines IA, calculs ponctuels. Payez uniquement ce que vous utilisez.</p>
            </div>
        </div>
        <div class="timeline-item">
            <div class="timeline-badge">5</div>
            <div class="timeline-content">
                <h4>Multi-Serveurs et Haute Disponibilité</h4>
                <p>Déployez sur plusieurs serveurs avec répartition de charge automatique. La réplication peer-to-peer assure la continuité de vos services.</p>
            </div>
        </div>
        <div class="timeline-item">
            <div class="timeline-badge">6</div>
            <div class="timeline-content">
                <h4>Assistants IA Intégrés</h4>
                <p>Des agents virtuels vous aident pour la modification de code et les opérations de déploiement, directement depuis la plateforme.</p>
            </div>
        </div>
    </div>
</div>

<!-- PAGE 4: INTERFACES & USE CASES -->
<div class="page">
    <h2>Une solution adaptée à chaque profil</h2>

    <h3>Modes d'accès</h3>
    <table class="interface-table">
        <tr>
            <th>Interface</th>
            <th>Usage</th>
            <th>Pour qui</th>
        </tr>
        <tr>
            <td><strong>Tableau de bord Web</strong></td>
            <td>Gestion visuelle complète</td>
            <td>Tous les utilisateurs</td>
        </tr>
        <tr>
            <td><strong>API REST</strong></td>
            <td>Intégration et automatisation</td>
            <td>Développeurs, CI/CD</td>
        </tr>
        <tr>
            <td><strong>CLI</strong></td>
            <td>Administration avancée</td>
            <td>Équipes DevOps</td>
        </tr>
        <tr>
            <td><strong>MCP</strong></td>
            <td>Communication inter-agents</td>
            <td>Agents GenAI</td>
        </tr>
    </table>

    <h3>Cas d'usage concrets</h3>
    <div class="usecase-grid">
        <div class="usecase-card">
            <div class="usecase-icon">🚀</div>
            <h4>Startup SaaS</h4>
            <p>Déployez votre produit, gérez les mises à jour et supervisez les performances. Pas besoin d'un DevOps dédié.</p>
        </div>
        <div class="usecase-card">
            <div class="usecase-icon">🧠</div>
            <h4>Équipe Data Science</h4>
            <p>Soumettez vos scripts IA en serverless avec accès GPU. Récupérez les résultats sans gérer l'infrastructure.</p>
        </div>
        <div class="usecase-card">
            <div class="usecase-icon">🏢</div>
            <h4>Entreprise Multi-Sites</h4>
            <p>Répliquez vos services sur plusieurs data centers avec synchronisation automatique et haute disponibilité.</p>
        </div>
        <div class="usecase-card">
            <div class="usecase-icon">🎨</div>
            <h4>Agence Web</h4>
            <p>Hébergez les applications de vos clients avec isolation, facturation individuelle et tableau de bord par client.</p>
        </div>
    </div>
</div>

<!-- PAGE 5: SECURITY & RESULTS -->
<div class="page">
    <h2>Sécurité et fiabilité de niveau entreprise</h2>

    <div class="features">
        <div class="feature-card">
            <h4>🛡️ Protection WAF</h4>
            <p>ModSecurity avec règles OWASP intégrées. Vos applications sont protégées contre les attaques web les plus courantes.</p>
        </div>
        <div class="feature-card">
            <h4>🔐 Authentification 2FA</h4>
            <p>Double authentification par TOTP ou email. SSO intégré pour une expérience utilisateur fluide et sécurisée.</p>
        </div>
        <div class="feature-card">
            <h4>🔒 Chiffrement SSL</h4>
            <p>Certificats SSL automatiques pour toutes vos applications. Communication chiffrée de bout en bout.</p>
        </div>
        <div class="feature-card">
            <h4>💾 Sauvegardes Automatiques</h4>
            <p>Backups horaires avec synchronisation S3. Restauration rapide en cas d'incident avec historique complet.</p>
        </div>
    </div>

    <h3>Ce que vous gagnez</h3>

    <div class="stats-row">
        <div class="stat-box">
            <div class="stat-number">90%</div>
            <div class="stat-label">Réduction du temps<br>de déploiement</div>
        </div>
        <div class="stat-box">
            <div class="stat-number">24/7</div>
            <div class="stat-label">Surveillance<br>automatique</div>
        </div>
        <div class="stat-box">
            <div class="stat-number">0</div>
            <div class="stat-label">Configuration<br>manuelle requise</div>
        </div>
    </div>

    <div class="highlight-box">
        <h4>📊 Visibilité complète sur vos coûts</h4>
        <p style="margin:0; font-size: 14px; color: #555;">
            Le système de facturation intégré suit l'utilisation de chaque application,
            génère des rapports et produit des factures PDF automatiquement.
            Maîtrisez votre budget IT en toute transparence.
        </p>
    </div>
</div>

<!-- PAGE 6: CTA -->
<div class="page">
    <h2>Prêt à simplifier votre infrastructure ?</h2>

    <p class="intro-text">
        @@PLATFORM_NAME@@ est conçu pour vous faire gagner du temps, réduire vos coûts
        et sécuriser vos applications. Rejoignez les équipes qui ont déjà choisi
        de se concentrer sur leur métier plutôt que sur l'infrastructure.
    </p>

    <ul class="benefits">
        <li>Démarrage rapide : votre première application déployée en moins de 5 minutes</li>
        <li>Support multilingue : interface disponible en Français et Anglais</li>
        <li>Évolutif : de 1 à N serveurs sans changement d'architecture</li>
        <li>Compatible IA : vos agents GenAI peuvent interagir via API et MCP</li>
        <li>Open source : transparence totale sur le fonctionnement de la plateforme</li>
    </ul>

    <div class="cta">
        <h3>Contactez-nous pour une démonstration</h3>
        <p>Notre équipe est disponible pour vous présenter la plateforme<br>et répondre à toutes vos questions.</p>
        <div class="contact">psmc@ovhcloud.com</div>
    </div>

    <div class="footer">
        <p>© PSMC OVHcloud — @@PLATFORM_NAME@@ • agentic-ai-plateform.com</p>
        <p style="font-size:10px; color:#bbb;">Simplifiez le déploiement, concentrez-vous sur votre métier.</p>
    </div>
</div>

</body>
</html>
"""

def build_html():
    """Return the marketing HTML with the configured platform name injected."""
    return html_template.replace("@@PLATFORM_NAME@@", PLATFORM_NAME)


if __name__ == "__main__":
    # Determine output path relative to this script's location
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(script_dir, f"{PLATFORM_SLUG}-Marketing.pdf")

    HTML(string=build_html()).write_pdf(output_path)
    print(f"PDF generated: {output_path}")
