# OncoPixel user manual / Manuel d'utilisation

*Designed to assist medical image analysis. Clinical judgment remains essential.*
*Conçu pour assister l'analyse d'images médicales. Le jugement clinique reste essentiel.*

The same text is available inside the application (Help page).

---

## English

### 1. First start
Create your local account (username, password with at least 8 characters including a letter and a digit). It protects the data on this computer; nothing is sent anywhere. After five wrong passwords sign-in is locked for a while, longer each time. When the account is created a **recovery key** is shown once: save it. If you forget your password, choose *Forgot your password?* on the sign-in page and enter your username, the recovery key and a new password (a new key is then issued). Without the key the password cannot be recovered. You can create a new key in Settings. The eye button shows or hides what you type.
Open **Models**: both models must say **Ready**. If one says *File missing* or *Does not match*, no analysis is possible and none is simulated; follow the hint shown.

### 2. Importing
**New analysis**: drop PNG or JPG images or a folder. Other formats are not imported. Choose *Separate studies* (one study per image) or *One series* (several slices in one study, scroll with the mouse wheel). Pick a patient or assign one later. For PNG/JPG enter the pixel spacing if you want millimetres. Images that cannot be read, are too small or are blank are refused; colour images are accepted with a warning and flagged for review.

### 3. Analysing
Open the study and press **Run analysis**.
- **Classification**: glioma, meningioma, pituitary tumor or no tumor, with a *model confidence estimate*. This is the classifier's score, not a calibrated clinical probability. Below the review threshold (default 90 %) the study is flagged.
- **Segmentation**: a tumor mask.
- If the two models disagree (for example "no tumor" but a mask), the study is flagged.

### 4. Viewer
Wheel: slices. Ctrl/⌘ + wheel: zoom. Drag: move. `0`: fit. Brightness, contrast and invert change only the display.

### 5. Correcting the mask
Brush `B` adds, eraser `E` removes, `[` `]` change size, Ctrl/⌘ Z undoes. Press **Save mask** (Ctrl/⌘ S). Measurements are recalculated from your corrected mask. Restore the model's mask at any time. Re-running the threshold replaces manual edits only after you confirm.

### 6. Measurements
Area, share of the image, bounding box, maximum, minimum and equivalent diameter, perimeter, circularity, aspect ratio, centroid, distance to the image midline, intensity statistics. 2D on the selected slice. No volume. The midline is the centre of the image, not an anatomical midline.

### 7. Review
In the *Report* tab write an optional note and press **Mark as reviewed**. Changing the result reopens the review. You can also flag a study manually.

### 8. Comparing
**Compare**: choose a patient and two segmented studies. You get the change in area and diameters, days between studies, and a mask overlay. Images are not registered: use the overlay only for the same acquisition geometry.

### 9. Exporting
Report PDF or Word (English or French), CSV, JSON, mask PNG, NIfTI, DICOM-SEG, DICOM SR. *Anonymize exports* leaves out name, history and physician. The folder button saves a copy to the export folder (Settings). DICOM files reference an 8-bit rendition of the slice included in the export.

### 10. Settings and backup
Theme, language, text size, high contrast, device (Automatic, MPS or CPU), review threshold, export folder. **Backup** creates one encrypted file protected by a passphrase; keep the passphrase, it cannot be recovered. **Restore** replaces the data on this computer.

### 11. Shortcuts
`1`–`7` sections, `?` help, `+` `-` zoom, `0` fit, `H` pan, `B`/`E` brush/eraser, `[` `]` brush size, Ctrl/⌘ Z / Shift Z undo/redo, Ctrl/⌘ S save mask.

### 12. Limits
Trained on 2D T1 slices of a public dataset (BRISC). Unknown performance on other scanners, sequences, planes or populations. Not a medical device. Not certified.

---

## Français

### 1. Premier démarrage
Créez votre compte local (nom d'utilisateur, mot de passe d'au moins 8 caractères avec une lettre et un chiffre). Il protège les données de cet ordinateur ; rien n'est envoyé ailleurs. Après cinq mots de passe erronés, la connexion est bloquée pour une durée croissante. À la création du compte, une **clé de récupération** s'affiche une seule fois : conservez-la. Si vous oubliez votre mot de passe, choisissez *Mot de passe oublié ?* sur la page de connexion et saisissez votre nom d'utilisateur, la clé et un nouveau mot de passe (une nouvelle clé est alors émise). Sans la clé, le mot de passe ne peut pas être récupéré. Vous pouvez créer une nouvelle clé dans les Paramètres. Le bouton en forme d'œil affiche ou masque la saisie.
Ouvrez **Modèles** : les deux modèles doivent indiquer **Prêt**. Si l'un indique *Fichier manquant* ou *Non conforme*, aucune analyse n'est possible et aucune n'est simulée ; suivez l'indication affichée.

### 2. Importer
**Nouvelle analyse** : déposez des images PNG ou JPG, ou un dossier. Les autres formats ne sont pas importés. Choisissez *Études séparées* (une étude par image) ou *Une série* (plusieurs coupes dans une étude, défilement à la molette). Choisissez un patient ou attribuez-le plus tard. Pour PNG/JPG, saisissez l'espacement des pixels pour obtenir des millimètres. Les images illisibles, trop petites ou vides sont refusées ; les images en couleur sont acceptées avec un avertissement et signalées.

### 3. Analyser
Ouvrez l'étude et appuyez sur **Lancer l'analyse**.
- **Classification** : gliome, méningiome, tumeur hypophysaire ou pas de tumeur, avec une *estimation de confiance du modèle*. C'est le score du classifieur, pas une probabilité clinique calibrée. Sous le seuil de vérification (90 % par défaut), l'étude est signalée.
- **Segmentation** : un masque tumoral.
- Si les deux modèles divergent (par exemple « pas de tumeur » mais un masque), l'étude est signalée.

### 4. Visualiseur
Molette : coupes. Ctrl/⌘ + molette : zoom. Glisser : déplacer. `0` : ajuster. Luminosité, contraste et inversion ne changent que l'affichage.

### 5. Corriger le masque
Pinceau `B` pour ajouter, gomme `E` pour retirer, `[` `]` pour la taille, Ctrl/⌘ Z pour annuler. Appuyez sur **Enregistrer le masque** (Ctrl/⌘ S). Les mesures sont recalculées à partir du masque corrigé. Vous pouvez restaurer le masque du modèle. Un nouveau seuil ne remplace vos corrections qu'après confirmation.

### 6. Mesures
Aire, part de l'image, boîte englobante, diamètres maximal, minimal et équivalent, périmètre, circularité, rapport d'aspect, centroïde, distance à la ligne médiane de l'image, statistiques d'intensité. En 2D sur la coupe choisie. Pas de volume. La ligne médiane est le centre de l'image, pas une ligne médiane anatomique.

### 7. Vérification
Dans l'onglet *Rapport*, écrivez une note facultative et appuyez sur **Marquer comme vérifiée**. Modifier le résultat rouvre la vérification. Vous pouvez aussi signaler une étude manuellement.

### 8. Comparer
**Comparer** : choisissez un patient et deux études segmentées. Vous obtenez l'évolution de l'aire et des diamètres, le nombre de jours entre les études et une superposition des masques. Les images ne sont pas recalées : n'utilisez la superposition que pour une même géométrie d'acquisition.

### 9. Exporter
Rapport PDF ou Word (anglais ou français), CSV, JSON, masque PNG, NIfTI, DICOM-SEG, DICOM SR. *Anonymiser les exports* omet le nom, les antécédents et le médecin. Le bouton dossier enregistre une copie dans le dossier d'export (Paramètres). Les fichiers DICOM font référence à une version 8 bits de la coupe incluse dans l'export.

### 10. Paramètres et sauvegarde
Thème, langue, taille du texte, contraste élevé, périphérique (Automatique, MPS ou CPU), seuil de vérification, dossier d'export. La **sauvegarde** crée un fichier chiffré protégé par une phrase secrète ; conservez-la, elle ne peut pas être récupérée. La **restauration** remplace les données de cet ordinateur.

### 11. Raccourcis
`1`–`7` sections, `?` aide, `+` `-` zoom, `0` ajuster, `H` déplacer, `B`/`E` pinceau/gomme, `[` `]` taille, Ctrl/⌘ Z / Maj Z annuler/rétablir, Ctrl/⌘ S enregistrer le masque.

### 12. Limites
Entraîné sur des coupes T1 2D d'un jeu de données public (BRISC). Performance inconnue sur d'autres scanners, séquences, plans ou populations. Pas un dispositif médical. Non certifié.
