import type { TDocumentDefinitions } from 'pdfmake/interfaces';
import { createBusinessPlanDefinition, type BusinessPlanSnapshot } from './definition';

export async function downloadBusinessPlan(snapshot: BusinessPlanSnapshot): Promise<void> {
  const filename = `geostart-business-plan-${snapshot.report.city}-${snapshot.report.niche}-${snapshot.calculatedAt.slice(0, 10)}.pdf`;
  await downloadPdf(createBusinessPlanDefinition(snapshot), filename);
}

export async function downloadPdf(
  definition: TDocumentDefinitions,
  filename: string,
): Promise<void> {
  const [{ default: pdfMake }, { default: fonts }] = await Promise.all([
    import('pdfmake/build/pdfmake'),
    import('pdfmake/build/vfs_fonts'),
  ]);
  pdfMake.addVirtualFileSystem(fonts);

  await pdfMake.createPdf(definition).download(filename);
}
