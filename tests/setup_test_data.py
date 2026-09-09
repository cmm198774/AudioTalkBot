import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import auth, storage

# 清理旧测试数据
try:
    storage.delete_session('testuser', '85996783c63448f19da6b0566378d716')
except:
    pass
try:
    storage.delete_session('testuser', '1f17c4e7cd8f4a72a3a4c58e707085da')
except:
    pass

# 创建测试用户
username = "testuser"
password = "test123"
try:
    auth.register(username, password)
    print("Created user: testuser / test123")
except:
    print("User already exists")

# 创建测试会话
session = storage.create_session(username, "你是一个法语老师，正在教学生基础法语。", "audio_text")
sid = session["id"]
print(f"Created session: {sid}")

# 填充对话到接近12800字符
messages = [
    ("user", "Bonjour! Je suis étudiant en français. Pouvez-vous m'aider?"),
    ("assistant", "Bonjour! Bien sûr, je suis ravi de vous aider à apprendre le français. Commençons par les bases. Comment vous appelez-vous?"),
    ("user", "Je m'appelle Simon. Et vous, comment vous appelez-vous?"),
    ("assistant", "Je m'appelle Marie. Enchantée, Simon! Le français est une belle langue. Aujourd'hui, nous allons apprendre les salutations et les présentations. Êtes-vous prêt?"),
    ("user", "Oui, je suis prêt! J'ai toujours voulu apprendre le français. C'est une langue très romantique."),
    ("assistant", "Merci pour ce compliment! Effectivement, le français est souvent appelé la langue de l'amour. Commençons par les salutations de base. 'Bonjour' signifie 'Good morning' ou 'Good day'. 'Bonsoir' signifie 'Good evening'. Et 'Bonne nuit' signifie 'Good night'. Pouvez-vous répéter ces trois expressions?"),
    ("user", "D'accord! Bonjour, bonsoir, bonne nuit. Est-ce que c'est correct?"),
    ("assistant", "Parfait! Votre prononciation est excellente. Maintenant, apprenons à nous présenter. 'Je m'appelle' signifie 'My name is'. Par exemple, 'Je m'appelle Marie' veut dire 'My name is Marie'. Et pour demander le nom de quelqu'un, on dit 'Comment vous appelez-vous?' Pouvez-vous essayer de vous présenter?"),
    ("user", "Je m'appelle Simon. Comment vous appelez-vous?"),
    ("assistant", "Très bien! Vous avez parfaitement compris. Maintenant, apprenons quelques expressions de politesse. 'Merci' signifie 'Thank you'. 'De rien' ou 'Je vous en prie' signifie 'You're welcome'. 'S'il vous plaît' signifie 'Please'. Ces expressions sont très importantes dans la culture française."),
    ("user", "Merci beaucoup! C'est très intéressant. J'aime apprendre ces expressions."),
    ("assistant", "De rien! Je suis heureuse que vous aimiez apprendre. La politesse est très importante en France. Les Français utilisent souvent ces expressions dans la vie quotidienne. Maintenant, apprenons à compter de un à dix. Un, deux, trois, quatre, cinq, six, sept, huit, neuf, dix. Pouvez-vous répéter?"),
    ("user", "Un, deux, trois, quatre, cinq, six, sept, huit, neuf, dix."),
    ("assistant", "Excellent! Vous apprenez très vite. Maintenant, apprenons quelques questions simples. 'Comment allez-vous?' signifie 'How are you?'. La réponse peut être 'Je vais bien, merci' (I'm fine, thank you) ou 'Ça va bien' (It's going well). Pouvez-vous me demander comment je vais?"),
    ("user", "Comment allez-vous?"),
    ("assistant", "Je vais très bien, merci! Et vous, comment allez-vous?"),
    ("user", "Je vais bien, merci. Le français est difficile?"),
    ("assistant", "Le français n'est pas très difficile si vous pratiquez régulièrement. La grammaire française a quelques règles complexes, comme les genres des noms (masculin et féminin) et les conjugaisons des verbes. Mais avec de la pratique, vous progresserez rapidement. Voulez-vous apprendre quelques phrases utiles pour les voyages?"),
    ("user", "Oui, s'il vous plaît! J'aimerais bien voyager en France un jour."),
    ("assistant", "Très bien! Apprenons quelques phrases utiles. 'Où est...?' signifie 'Where is...?'. Par exemple, 'Où est la gare?' (Where is the train station?). 'Je voudrais...' signifie 'I would like...'. Par exemple, 'Je voudrais un café' (I would like a coffee). 'Combien ça coûte?' signifie 'How much does it cost?'. Ces phrases vous seront très utiles en voyage."),
    ("user", "Où est la gare? Je voudrais un café. Combien ça coûte?"),
    ("assistant", "Parfait! Vous utilisez déjà ces phrases correctement. Continuons avec d'autres expressions utiles. 'Je ne comprends pas' signifie 'I don't understand'. 'Pouvez-vous répéter, s'il vous plaît?' signifie 'Can you repeat, please?'. 'Parlez-vous anglais?' signifie 'Do you speak English?'. Ces phrases vous aideront si vous avez des difficultés à communiquer."),
    ("user", "Je ne comprends pas. Pouvez-vous répéter, s'il vous plaît?"),
    ("assistant", "Bien sûr! Je vais répéter plus lentement. 'Je ne comprends pas' - I don't understand. 'Pouvez-vous répéter, s'il vous plaît?' - Can you repeat, please. Ces phrases sont très utiles quand vous ne comprenez pas quelque chose. Les Français apprécieront vos efforts pour communiquer en français."),
    ("user", "Merci! Vous êtes très patiente."),
    ("assistant", "C'est mon plaisir! L'enseignement est ma passion. Continuons avec quelques expressions pour les restaurants. 'La carte, s'il vous plaît' signifie 'The menu, please'. 'Je voudrais commander' signifie 'I would like to order'. 'L'addition, s'il vous plaît' signifie 'The bill, please'. En France, il est poli de dire 'Bonjour' en entrant dans un restaurant et 'Au revoir' en partant."),
    ("user", "La carte, s'il vous plaît. Je voudrais commander. L'addition, s'il vous plaît."),
    ("assistant", "Excellent! Vous progressez très bien. Apprenons maintenant les jours de la semaine. Lundi (Monday), mardi (Tuesday), mercredi (Wednesday), jeudi (Thursday), vendredi (Friday), samedi (Saturday), dimanche (Sunday). En français, les jours de la semaine ne prennent pas de majuscule, contrairement à l'anglais. Pouvez-vous me dire quel jour nous sommes?"),
    ("user", "Aujourd'hui, c'est quel jour?"),
    ("assistant", "Aujourd'hui, c'est lundi. Et demain, ce sera mardi. Les mois en français sont: janvier, février, mars, avril, mai, juin, juillet, août, septembre, octobre, novembre, décembre. Comme les jours, les mois ne prennent pas de majuscule en français."),
    ("user", "Janvier, février, mars, avril, mai, juin, juillet, août, septembre, octobre, novembre, décembre."),
    ("assistant", "Très bien! Vous avez une bonne mémoire. Continuons avec les couleurs. Rouge (red), bleu (blue), vert (green), jaune (yellow), noir (black), blanc (white), gris (gray), orange (orange), rose (pink), violet (purple). Les couleurs en français s'accordent en genre et en nombre avec le nom qu'elles qualifient."),
    ("user", "Rouge, bleu, vert, jaune, noir, blanc, gris, orange, rose, violet."),
    ("assistant", "Parfait! Maintenant, apprenons quelques expressions pour faire les courses. 'Combien ça coûte?' signifie 'How much does it cost?'. 'C'est trop cher' signifie 'It's too expensive'. 'Je vais prendre celui-ci' signifie 'I'll take this one'. 'Avez-vous une taille plus grande?' signifie 'Do you have a larger size?'. Ces phrases vous seront utiles dans les boutiques."),
    ("user", "Combien ça coûte? C'est trop cher. Je vais prendre celui-ci."),
    ("assistant", "Excellent! Vous utilisez déjà ces expressions naturellement. Continuons avec les nombres de dix à vingt. Dix (10), onze (11), douze (12), treize (13), quatorze (14), quinze (15), seize (16), dix-sept (17), dix-huit (18), dix-neuf (19), vingt (20). Les nombres français ont des particularités, comme 'soixante-dix' pour 70 (littéralement 'sixty-ten')."),
    ("user", "Dix, onze, douze, treize, quatorze, quinze, seize, dix-sept, dix-huit, dix-neuf, vingt."),
    ("assistant", "Très bien! Vous apprenez rapidement. Apprenons maintenant à exprimer nos goûts. 'J'aime' signifie 'I like'. 'Je n'aime pas' signifie 'I don't like'. 'J'adore' signifie 'I love'. 'Je déteste' signifie 'I hate'. Par exemple, 'J'aime le café' (I like coffee), 'Je n'aime pas le thé' (I don't like tea). Qu'est-ce que vous aimez en français?"),
    ("user", "J'aime le français. J'adore la culture française. Je n'aime pas les difficultés."),
    ("assistant", "C'est une excellente attitude! Tout le monde rencontre des difficultés en apprenant une nouvelle langue, mais l'important est de persévérer. Vous faites déjà d'excellents progrès. Continuons avec quelques expressions pour demander son chemin. 'Excusez-moi' signifie 'Excuse me'. 'Où est...?' signifie 'Where is...?'. 'Comment puis-je aller à...?' signifie 'How can I go to...?'. 'C'est loin d'ici?' signifie 'Is it far from here?'."),
    ("user", "Excusez-moi, où est la tour Eiffel? Comment puis-je aller au Louvre?"),
    ("assistant", "Très bien! Pour répondre: 'La tour Eiffel est au Champ de Mars' (The Eiffel Tower is at Champ de Mars). 'Pour aller au Louvre, vous pouvez prendre le métro' (To go to the Louvre, you can take the metro). 'C'est à environ vingt minutes à pied' (It's about twenty minutes on foot). Ces expressions vous aideront à vous orienter dans Paris."),
    ("user", "Merci beaucoup! J'aimerais visiter Paris un jour."),
    ("assistant", "Ce serait merveilleux! Paris est une ville magnifique avec beaucoup de choses à voir. La tour Eiffel, le Louvre, Notre-Dame, les Champs-Élysées, Montmartre... Chaque quartier a son propre charme. Quand vous visiterez Paris, n'oubliez pas d'essayer la cuisine française. Les croissants, les baguettes, le fromage, le vin... C'est délicieux!"),
    ("user", "J'aime les croissants et le fromage. Le vin français est très célèbre."),
    ("assistant", "Effectivement! La France est célèbre pour son vin et sa gastronomie. Les régions viticoles les plus connues sont la Bourgogne, Bordeaux, la Champagne, et la vallée du Loire. Chaque région a ses spécialités. En France, le repas est un moment important. Les Français prennent le temps de manger et de profiter de la nourriture."),
    ("user", "C'est intéressant. En Chine, nous aussi, nous aimons prendre le temps de manger."),
    ("assistant", "C'est vrai! Les deux cultures partagent cette valeur. En France, le déjeuner est souvent pris entre midi et deux heures, et le dîner vers huit ou neuf heures. Les Français aiment commencer le repas par une entrée, puis le plat principal, ensuite le fromage, et enfin le dessert. C'est un art de vivre."),
    ("user", "J'aimerais apprendre plus sur la culture française."),
    ("assistant", "Avec plaisir! La culture française est riche et diversifiée. La France est connue pour sa littérature (Victor Hugo, Marcel Proust, Albert Camus), son cinéma (Nouvelle Vague, Cannes Film Festival), sa mode (Paris Fashion Week), et ses arts (Impressionnisme, Monet, Renoir). Les Français sont aussi très fiers de leur langue et de leur patrimoine."),
    ("user", "Qu'est-ce que la Nouvelle Vague?"),
    ("assistant", "La Nouvelle Vague est un mouvement cinématographique français des années 1950 et 1960. Des réalisateurs comme Jean-Luc Godard, François Truffaut et Claude Chabrol ont révolutionné le cinéma avec des techniques innovantes. Leurs films étaient caractérisés par des plans longs, des dialogues naturels et une narration non linéaire. Ce mouvement a eu une influence mondiale sur le cinéma moderne."),
    ("user", "C'est très intéressant. Et l'Impressionnisme?"),
    ("assistant", "L'Impressionnisme est un mouvement artistique né en France dans la seconde moitié du XIXe siècle. Les peintres impressionnistes comme Claude Monet, Pierre-Auguste Renoir, Edgar Degas et Camille Pissarro cherchaient à capturer la lumière et les couleurs de manière spontanée. Ils peignaient souvent en plein air pour saisir les effets changeants de la lumière naturelle. Le terme 'impressionnisme' vient du tableau de Monet 'Impression, soleil levant'.Ce mouvement a révolutionné l'art en rompant avec les conventions académiques de l'époque."),
    ("user", "J'aime beaucoup les tableaux de Monet. Les nymphéas sont magnifiques."),
    ("assistant", "Absolument! Les Nymphéas de Monet sont une série d'environ 250 peintures à l'huile représentant son jardin à Giverny. Monet a travaillé sur cette série pendant les 30 dernières années de sa vie. Ces tableaux capturent les reflets de l'eau, les nuances de lumière et les changements de saisons. Aujourd'hui, les Nymphéas sont exposés au Musée de l'Orangerie à Paris dans des salles spécialement conçues pour les accueillir."),
    ("user", "J'aimerais visiter le Musée de l'Orangerie un jour."),
    ("assistant", "Ce serait une expérience inoubliable! Le Musée de l'Orangerie est situé dans le Jardin des Tuileries, près du Louvre. En plus des Nymphéas de Monet, le musée possède une remarquable collection d'œuvres impressionnistes et post-impressionnistes, incluant des tableaux de Renoir, Cézanne, Matisse, Modigliani et Picasso. C'est un musée plus petit que le Louvre, mais tout aussi fascinant."),
    ("user", "Merci pour toutes ces informations. J'ai beaucoup appris aujourd'hui."),
    ("assistant", "C'était un plaisir de vous enseigner! Vous avez fait d'excellents progrès en français aujourd'hui. Continuez à pratiquer tous les jours, même si c'est juste quelques minutes. Écoutez de la musique française, regardez des films avec sous-titres, lisez des livres simples. L'immersion est la clé de l'apprentissage d'une langue. N'hésitez pas à revenir si vous avez d'autres questions."),
]

# 添加对话记录
for i, (role, text) in enumerate(messages):
    storage.append_transcript(username, sid, role, text)

# 计算当前上下文大小
session = storage.get_session(username, sid)
transcript = session["transcript"]
chars = sum(len(item.get("text", "")) for item in transcript)
print(f"Session: {len(transcript)} items, {chars} chars")
print(f"Threshold: 12800 chars")
print(f"Status: {'READY' if chars > 12800 else 'NEED MORE'}")
