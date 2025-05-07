# SI_Agent: Search, Download, Analyze Supplementary Information Files
* Search is performed via the Publish or Perish (PoP) software. [Link](https://harzing.com/resources/publish-or-perish)
  * Once a search is performed, results are saved in a `.csv` file, with the name format = `PoPCites-Keyword-Journal.csv`
  * The `.csv` files are stored in `Searches/` folder, categorized by the publishers
* The papers stored in `.csv` files are then cleaned, categorized and labeled by their keyword. For example, a paper can have multiple keywords: `['Oxidative Addition', 'Cross Coupling', 'Homogeneous Catalysis']`
* SI Downloads are then performed using the scripts in `File_Download/` folder
* After files being downloaded, **Stirling PDF** server version is used to massively convert PDF to .txt files. The **`Curl script`** is in `PDF_To_Text` folder.
  * :memo: Note that an Unix machine (such as Ubuntu) is needed

