import { createBusinessPlanDefinition, type BusinessPlanSnapshot } from './definition';

export async function downloadBusinessPlan(snapshot: BusinessPlanSnapshot): Promise<void> {
  const [{ default: pdfMake }, { default: fonts }] = await Promise.all([
    import('pdfmake/build/pdfmake'),
    import('pdfmake/build/vfs_fonts'),
  ]);
  pdfMake.addVirtualFileSystem(fonts);
  const definition = createBusinessPlanDefinition(snapshot);
  const filename = `geostart-business-plan-${snapshot.report.city}-${snapshot.report.niche}-${snapshot.calculatedAt.slice(0, 10)}.pdf`;
  await pdfMake.createPdf(definition).download(filename);
}
