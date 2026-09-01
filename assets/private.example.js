/* Образец. Скопируйте в assets/private.js и подставьте свои данные:
       cp assets/private.example.js assets/private.js

   assets/private.js в .gitignore и наружу не уходит. Он подставляет личные
   данные в резюме, которое вы печатаете в PDF (Cmd+P) и отправляете адресно.
   На опубликованном сайте этого файла нет, поэтому страница остаётся
   обезличенной: без телефона и без названия работодателя. */
document.getElementById("private-phone").textContent = "+7 000 000-00-00";
document.getElementById("employer").textContent = "«Название компании», город";
