# Convierte el PDF *_Data_Model.pdf de cada módulo (excluye los *_Diagram.pdf).
# Requiere el venv activado: .\.venv\Scripts\Activate.ps1
# Cada módulo escribe su resultado en su propia subcarpeta dentro de output\.
# Las tablas van a CSV/JSON vía PyMuPDF (rápido, no depende del modo de Docling).

pdf2md convert "input\Agents Commissions Module\Commissions_Data_Model.pdf" -o "output\Agents Commissions Module" -v
pdf2md convert "input\Annuity Module\Annuity_Data_Model.pdf" -o "output\Annuity Module" -v
pdf2md convert "input\Authorization Matrix Module\Authorization_Matrix_Data_Model.pdf" -o "output\Authorization Matrix Module" -v
pdf2md convert "input\Billing and Collection Module\Billing_and_Collection_Data_Model.pdf" -o "output\Billing and Collection Module" -v
pdf2md convert "input\Classic Claims Module\Classic_Claims_Data_Model.pdf" -o "output\Classic Claims Module" -v
pdf2md convert "input\Closing Period Operations Module\Closing_Period_Operations_Data_Model.pdf" -o "output\Closing Period Operations Module" -v
pdf2md convert "input\Currencies Module\Currencies_Data_Model.pdf" -o "output\Currencies Module" -v
pdf2md convert "input\Data Acquisition Module\Data_Acquisition_Data_Model.pdf" -o "output\Data Acquisition Module" -v
pdf2md convert "input\Life Math Module\Life_Math_Data_Model.pdf" -o "output\Life Math Module" -v
pdf2md convert "input\Modernized Claims Module\Modernized_Claims_Data_Model.pdf" -o "output\Modernized Claims Module" -v
pdf2md convert "input\Need Assessment Module\Need_Assessment_Data_Model.pdf" -o "output\Need Assessment Module" -v
pdf2md convert "input\Network Module\Network_Module_Data_Model.pdf" -o "output\Network Module" -v
pdf2md convert "input\Nomenclatures Module\Nomenclatures_Data_Model.pdf" -o "output\Nomenclatures Module" -v
pdf2md convert "input\Object Administration Module\Object_Administration_Data_Model.pdf" -o "output\Object Administration Module" -v
pdf2md convert "input\PAS Providers Module\PAS_Providers_Data_Model.pdf" -o "output\PAS Providers Module" -v
pdf2md convert "input\People Module\People_Data_Model.pdf" -o "output\People Module" -v
pdf2md convert "input\Policy Administration Module\Policy_Administration_Data_Model.pdf" -o "output\Policy Administration Module" -v
pdf2md convert "input\Product Configurator Module\Product_Configurator_Data_Model.pdf" -o "output\Product Configurator Module" -v
pdf2md convert "input\Reinsurance Module\Reinsurance_Data_Model.pdf" -o "output\Reinsurance Module" -v
pdf2md convert "input\Service Orchestration Module\Service_Orchestration_Data_Model.pdf" -o "output\Service Orchestration Module" -v
pdf2md convert "input\Unit Link Module\Unit_Link_Data_Model.pdf" -o "output\Unit Link Module" -v

# Catálogo consolidado: cruza entidades y foreign keys de todos los módulos
# ya convertidos arriba en un solo schema_catalog.json / schema_catalog.md.
pdf2md catalog output
