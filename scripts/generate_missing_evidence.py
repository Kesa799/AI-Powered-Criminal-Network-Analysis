import os
import html
from pathlib import Path
from backend.database import SessionLocal
from backend.models import EvidenceItemModel, EvidenceSourceModel, EvidenceMentionModel
from backend.config import settings

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Preformatted
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

def generate_evidence_pdf(item: EvidenceItemModel, db) -> Path:
    target_path = settings.originals_dir / (item.sha256 if item.sha256 else item.evidence_id)
    target_path.parent.mkdir(parents=True, exist_ok=True)

    sources = db.query(EvidenceSourceModel).filter(
        EvidenceSourceModel.evidence_id == item.evidence_id
    ).order_by(EvidenceSourceModel.page, EvidenceSourceModel.row, EvidenceSourceModel.id).all()

    mentions = db.query(EvidenceMentionModel).filter(
        EvidenceMentionModel.evidence_id == item.evidence_id
    ).all()

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=14,
        leading=18,
        textColor=colors.HexColor('#0f172a'),
        spaceAfter=4
    )
    subtitle_style = ParagraphStyle(
        'DocSubTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#2563eb'),
        spaceAfter=10
    )
    meta_label = ParagraphStyle('ML', fontName='Helvetica-Bold', fontSize=8.5, leading=11, textColor=colors.HexColor('#475569'))
    meta_val = ParagraphStyle('MV', fontName='Helvetica', fontSize=8.5, leading=11, textColor=colors.HexColor('#0f172a'))
    page_header = ParagraphStyle('PH', fontName='Helvetica-Bold', fontSize=10, leading=13, textColor=colors.HexColor('#1e293b'), spaceAfter=4)
    body_style = ParagraphStyle('DB', fontName='Courier', fontSize=8, leading=11, textColor=colors.HexColor('#0f172a'))

    elements = []
    elements.append(Paragraph('CENTRAL INVESTIGATION DEPARTMENT &mdash; EVIDENCE DOSSIER', title_style))
    elements.append(Paragraph(f'Case Exhibit: {item.filename} &bull; Case ID: {item.case_id}', subtitle_style))

    sha_disp = html.escape(item.sha256 or 'N/A')
    uploader_disp = html.escape(item.uploader or 'Investigator')
    meta_data = [
        [Paragraph('<b>Evidence ID:</b>', meta_label), Paragraph(html.escape(item.evidence_id or ''), meta_val),
         Paragraph('<b>Classification:</b>', meta_label), Paragraph(html.escape(item.job_classification or item.category or 'Document'), meta_val)],
        [Paragraph('<b>Uploader:</b>', meta_label), Paragraph(uploader_disp, meta_val),
         Paragraph('<b>Uploaded At:</b>', meta_label), Paragraph(html.escape(str(item.uploaded_at or 'N/A')[:19]), meta_val)],
        [Paragraph('<b>SHA-256:</b>', meta_label), Paragraph(f'<font size="6">{sha_disp}</font>', meta_val),
         Paragraph('<b>Status:</b>', meta_label), Paragraph(html.escape(item.status or 'Verified'), meta_val)],
    ]
    t = Table(meta_data, colWidths=[80, 180, 80, 180])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#cbd5e1')),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
        ('TOPPADDING', (0,0), (-1,-1), 4),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 14))

    if sources:
        # Group by page
        pages_dict = {}
        for s in sources:
            p_num = s.page or 1
            pages_dict.setdefault(p_num, []).append(s.text or '')

        for p_num in sorted(pages_dict.keys()):
            elements.append(Paragraph(f'<b>Extracted Document Content &mdash; Page {p_num}</b>', page_header))
            combined_page_text = '\n'.join([t for t in pages_dict[p_num] if t.strip()])
            clean_text = combined_page_text.replace('\t', '    ')
            if clean_text.strip():
                elements.append(Preformatted(clean_text, body_style))
            else:
                elements.append(Paragraph('<i>[Empty text record on this page]</i>', styles['Italic']))
            elements.append(Spacer(1, 12))
    elif mentions:
        elements.append(Paragraph('<b>Extracted Forensic Entities & Intelligence</b>', page_header))
        elements.append(Spacer(1, 4))
        mention_rows = [
            [Paragraph('<b>Entity Type</b>', meta_label),
             Paragraph('<b>Identifier / Name</b>', meta_label),
             Paragraph('<b>Role</b>', meta_label),
             Paragraph('<b>Evidence Quote / Mention</b>', meta_label)]
        ]
        for m in mentions[:30]:
            mention_rows.append([
                Paragraph(html.escape(m.type or 'Entity'), meta_val),
                Paragraph(html.escape(m.raw_value or m.normalized_value or ''), meta_val),
                Paragraph(html.escape(m.role or 'Mentioned'), meta_val),
                Paragraph(html.escape((m.quote or '')[:100]), meta_val),
            ])
        mt = Table(mention_rows, colWidths=[90, 120, 80, 230])
        mt.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#e2e8f0')),
            ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#cbd5e1')),
            ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
            ('TOPPADDING', (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ]))
        elements.append(mt)
        elements.append(Spacer(1, 12))
    else:
        elements.append(Paragraph('<b>Forensic Custody Notice</b>', page_header))
        elements.append(Spacer(1, 4))
        elements.append(Paragraph(
            'This evidence item was ingested into the ATLAS Crime Analysis System. '
            'Its forensic hash and chain of custody are recorded in the audit trail.',
            styles['Normal']
        ))

    doc = SimpleDocTemplate(
        str(target_path),
        pagesize=A4,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )
    doc.build(elements)
    return target_path

if __name__ == '__main__':
    db = SessionLocal()
    item = db.query(EvidenceItemModel).filter(EvidenceItemModel.evidence_id == 'EV-6c2f30e60cec').first()
    path = generate_evidence_pdf(item, db)
    print(f'Successfully created {path}, size: {path.stat().st_size} bytes')
