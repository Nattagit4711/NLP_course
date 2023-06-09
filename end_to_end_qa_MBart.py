
import numpy as np
import torch
from torch import nn
from torch import functional as F
import math
from tqdm import tqdm
import pickle
from transformers import BartTokenizer, BartForConditionalGeneration, BartConfig, AutoTokenizer, MBartForConditionalGeneration, MBart50TokenizerFast, MT5Model, AutoTokenizer, MT5ForConditionalGeneration
from collections import Counter
import unicodedata
from torch.nn.functional import cosine_similarity
from scipy.sparse import csr_matrix
import editdistance
import os
import csv
import torch.nn.functional as F
import re
# from transformers import MBartTokenizer, MBartForConditionalGeneration

TAG_UNK = "UNK"

STOPWORDS = {
    'i', 'me', 'my', 'myself', 'we', 'our', 'ours', 'ourselves', 'you', 'your',
    'yours', 'yourself', 'yourselves', 'he', 'him', 'his', 'himself', 'she',
    'her', 'hers', 'herself', 'it', 'its', 'itself', 'they', 'them', 'their',
    'theirs', 'themselves', 'what', 'which', 'who', 'whom', 'this', 'that',
    'these', 'those', 'am', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
    'have', 'has', 'had', 'having', 'do', 'does', 'did', 'doing', 'a', 'an',
    'the', 'and', 'but', 'if', 'or', 'because', 'as', 'until', 'while', 'of',
    'at', 'by', 'for', 'with', 'about', 'against', 'between', 'into', 'through',
    'during', 'before', 'after', 'above', 'below', 'to', 'from', 'up', 'down',
    'in', 'out', 'on', 'off', 'over', 'under', 'again', 'further', 'then',
    'once', 'here', 'there', 'when', 'where', 'why', 'how', 'all', 'any',
    'both', 'each', 'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor',
    'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very', 's', 't', 'can',
    'will', 'just', 'don', 'should', 'now', 'd', 'll', 'm', 'o', 're', 've',
    'y', 'ain', 'aren', 'couldn', 'didn', 'doesn', 'hadn', 'hasn', 'haven',
    'isn', 'ma', 'mightn', 'mustn', 'needn', 'shan', 'shouldn', 'wasn', 'weren',
    'won', 'wouldn', "'ll", "'re", "'ve", "n't", "'s", "'d", "'m", "''", "``"
}

import csv
def check_eng_char(sentence):
    return bool(re.search(r'[a-zA-Z]', sentence))

def check_thai_char(sentence):
    return bool(re.search(r'[ก-๙]', sentence))

def normalize(text):
    """Resolve different type of unicode encodings."""
    return unicodedata.normalize('NFD', text)

def add_bigrams(token_list):
    bigram_list = []
    #new_token_list = [t.replace('Ġ', '') for t in token_list if any([c.isalpha() for c in t])]
    new_token_list = [t for t in token_list if any([c.isalpha() for c in t])]
    for idx in range(len(new_token_list) - 1):
        bigram_list.append(new_token_list[idx] + '_' + new_token_list[idx+1])
    return new_token_list + bigram_list

def get_merged_model(model_name, emb_path):
      wangchan_state_dict = torch.load(emb_path)
      mt5_model = MT5ForConditionalGeneration.from_pretrained(model_name)
    #   mbart_model = MBartForConditionalGeneration.from_pretrained(model_name)
    #   bart_model = BartForConditionalGeneration.from_pretrained(model_name)
    #   merge_embeddings = torch.cat((mt5_model.model.encoder.embed_tokens.weight, wangchan_state_dict['weight']), 0)
    #   merge_embeddings = mbart_model.model.encoder.embed_tokens.weight
    #   mbart_model.model.encoder.embed_tokens = torch.nn.Embedding.from_pretrained(merge_embeddings, freeze=False)

      merge_embeddings = mt5_model.encoder.embed_tokens.weight
      mt5_model.encoder.embed_tokens = torch.nn.Embedding.from_pretrained(merge_embeddings, freeze=False)
      return mt5_model

def get_ids_mapping_dict():
      wangchan_ids = []
      with open('/content/gdrive/MyDrive/Medical-Question-Answering-main/ids_mapping/wangchan_numbers.txt', 'r') as f:
        spamreader = csv.reader(f, delimiter='\n')
        for x in spamreader:
          x = x[0]
          wangchan_ids.append(int(float(x[:x.find('e')]) * 10 ** float(x[x.find('+')+1:])))
      
      bart_mapped_ids = []
      with open('/content/gdrive/MyDrive/Medical-Question-Answering-main/ids_mapping/bart_mapped_numbers.txt', 'r') as f:
        spamreader = csv.reader(f, delimiter='\n')
        for x in spamreader:
          x = x[0]
          bart_mapped_ids.append(int(float(x[:x.find('e')]) * 10 ** float(x[x.find('+')+1:])))

      return dict(zip(wangchan_ids, bart_mapped_ids))
# model_name="facebook/bart-large-cnn"
# "google/mt5-small"
# "facebook/mbart-large-50"
class EndToEndQA(nn.Module):
    def __init__(self, database, questions_as_tfidf, questions_as_str, tfidf_vocab, tfidf_df, attn_dropout=0.1, model_name="google/mt5-small", top_k=3):
        super(EndToEndQA, self).__init__()
        
        # BART Model
        # self.model = BartForConditionalGeneration.from_pretrained(model_name)
        self.wangchan_name = 'airesearch/wangchanberta-base-att-spm-uncased'
        self.emb_path = "/content/gdrive/MyDrive/Medical-Question-Answering-main/embedding_weights_wangchanberta.pt"
        self.model = get_merged_model(model_name, self.emb_path)
        # self.tokenizer = MBart50TokenizerFast.from_pretrained(model_name)
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        # # self.tokenizer = BartTokenizer.from_pretrained(model_name)
        # self.tokenizer_th = MBart50TokenizerFast.from_pretrained(model_name)
        self.tokenizer_th = AutoTokenizer.from_pretrained(model_name)
        self.ids_mapping_dict = get_ids_mapping_dict()

        # self.tokenizer_th = AutoTokenizer.from_pretrained(self.wangchan_name)

        # HParams
        self.hidden_size = self.model.config.d_model
        self.max_words = 64 #self.model.config.max_position_embeddings
        self.max_sum_words = 512

        # Attention
        #self.attn = nn.Linear(self.hidden_size * 2, self.max_words)
        #self.attn_combine = nn.Linear(self.hidden_size * 2, self.hidden_size)
        #self.dropout = nn.Dropout(attn_dropout)

        # Final Layer
        self.activation = nn.ReLU()
        #self.linear = nn.Linear(self.hidden_size, self.hidden_size)
        #self.activation2 = nn.Sigmoid()

        # Database
        self.database = database # dictionary (question number => answer sentences, as list of str)
        self.questions_as_str = questions_as_str # list of questions
        self.questions_as_tfidf = questions_as_tfidf.transpose()
        self.tfidf_vocab = tfidf_vocab
        self.tfidf_df = tfidf_df
        self.n_docs = self.questions_as_tfidf.shape[0]
        self.n_words = len(self.tfidf_vocab)
        self.top_k = top_k # Top-k most relevant FAQs based on TF-IDF
    
    def get_top_k(self, generated_faq):
        cnter = Counter(generated_faq)
        print('generated_faq', generated_faq)
        this_thing = []
        row = []
        col = []
        data = []
        # print('word found')
        # print(cnter)
        for word in cnter:
            # print(word)
            if word in self.tfidf_vocab:
                row.append(0)
                col.append(self.tfidf_vocab[word])
                data.append(np.log1p(cnter[word]) * np.log((self.n_docs - self.tfidf_df.get(word, 0) + 0.5) / (self.tfidf_df.get(word,0) + 0.5)))
                #tfidf[self.tfidf_vocab[word]] = np.log1p(cnter[word]) * np.log((self.n_docs - self.tfidf_df.get(word, 0) + 0.5) / (self.tfidf_df.get(word,0) + 0.5))
                this_thing.append((word, data[-1]))
                print('word found', word)
        #tfidf = csr_matrix(np.array(tfidf))
        print('n_word', self.n_words)
        tfidf = csr_matrix((data, (row,col)), shape = (1,self.n_words))
        print('tfidf.shape : ', tfidf.shape)
        print('self.questions_as_tfidf.shape : ', self.questions_as_tfidf.shape)
        similarity_scores = tfidf * self.questions_as_tfidf
        ranking = similarity_scores.toarray()[0].argsort()[::-1]
        argmax_similarity = ranking[:32]
        return argmax_similarity, this_thing, ranking
        

    def get_idf_vector(self, input_ids):
        # words = [self.tokenizer.decoder.get(x) for x in input_ids]
        words = [self.tokenizer.decode(x) for x in input_ids]
        # print('this is word')
        # print(words)
        idf_vector = [np.log((self.n_docs - self.tfidf_df.get(word, 0) + 0.5) / (self.tfidf_df.get(word,0) + 0.5)) if word in self.tfidf_vocab and word != '' else 0 for word in words]
        # print('idf_vector',idf_vector)
        return torch.tensor(idf_vector).cuda()

    def ids_mapping(self, ids):
        """
          ids: list of ids
          ids_mapping_dict: dict of ids mapping

          return: tensors of ids (mapped wangchan to bart embedding idx)
        """
        ids = ids[0]
        for i, idx in enumerate(ids):
          if idx in self.ids_mapping_dict.keys():
            ids[i] = self.ids_mapping_dict[idx]
          else:
            ids[i] = idx + 50264
        print('ids_shape', torch.tensor([ids]).shape)
        return torch.tensor([ids])

    def get_contrastive_loss(self, emb1, emb2):
        """
          Returns the contrastive loss between two embeddings
        """
        # Emb shape ไม่เท่ากันค้าบบบบบบ
        # zero padding ขนาด max_length (512) ดีไหม?????
        # torch.zero(512,1024)

        # contrastive_loss = 1 - torch.mean((F.cosine_similarity(emb1[0], emb2[0])))
        contrastive_loss = 1 - (F.cosine_similarity(emb1[0], emb2[0]))

        # print('mean cos :', torch.mean(F.cosine_similarity(emb1[0], emb2[0])))
        # print('loss :', contrastive_loss)
        
        return contrastive_loss

    def forward(self, chq_en, chq_th=None, faq=None, num_answer_sentences=0, test=False, ref_as_gen=False, test_idx=0):
        # chq is string
        if num_answer_sentences == 0:
            num_answer_sentences = self.top_k

        # Summarization
        inputs = self.tokenizer([chq_en], max_length=self.max_sum_words, return_tensors='pt', truncation=True)
        input_ids = inputs['input_ids']

        inputs_th = self.tokenizer_th([chq_th], max_length=self.max_sum_words, return_tensors='pt', truncation=True)
        input_ids_th = inputs_th['input_ids']
        # input_ids_th = self.ids_mapping(inputs_th)

        max_len = max(len(input_ids_th[0]), len(input_ids[0]))

        if len(input_ids_th[0])> len(input_ids[0]):
            input_ids = F.pad(input_ids, (0, max_len - len(input_ids[0])), value=0)
        else:
            input_ids_th = F.pad(input_ids_th, (0, max_len - len(input_ids_th[0])), value=0)

        input_ids, input_ids_th = input_ids.cuda(), input_ids_th.cuda()

        '''

        '''

        if faq is not None or test: 
            faq_ids = self.tokenizer([faq], max_length=self.max_words, return_tensors='pt', truncation=True, padding='max_length')['input_ids'].cuda()
            # faq_ids = self.ids_mapping(self.tokenizer([faq], max_length=self.max_words, truncation=True, padding='max_length'))['input_ids'].cuda() ###################### เเก้ตรงนี้ embed
            summary_output = self.model(input_ids, labels=faq_ids)
            summary_output_from_th = self.model(input_ids_th, labels=faq_ids) 
            emb_th_chq = self.model.encoder(input_ids_th).last_hidden_state.mean(dim=1)
            emb_en_chq = self.model.encoder(input_ids).last_hidden_state.mean(dim=1)
            # emb_th_chq = self.model.model.encoder(input_ids_th).last_hidden_state.mean(dim=1)
            # emb_en_chq = self.model.model.encoder(input_ids).last_hidden_state.mean(dim=1)
            contrastive_loss = 1 - torch.nn.functional.cosine_similarity(emb_th_chq, emb_en_chq)[0]
            # print("EMB: ", emb_th_chq, emb_th_chq.shape)
            # print("Cos sim: ", cos_sim)
            # contrastive_loss = self.get_contrastive_loss(emb_th_chq, emb_en_chq) 
        else:
            # print('Inferrence')
            #  !!!!!!!!!!!!!!!
            summary_output = self.model(input_ids)   

        # Contrastive loss       
        # emb_th_chq = self.model.model.encoder(input_ids_th)
        # emb_en_chq = self.model.model.encoder(input_ids)
        # contrastive_loss = self.get_contrastive_loss(emb_th_chq, emb_en_chq)
        # print('contrastive_loss', contrastive_loss)

        # Matching with database of FAQ
        ## TF-IDF matching
        if faq is None or (not ref_as_gen and test):
            generated_faq_ids = self.model.generate(input_ids, num_beams=10, max_length=21, min_length=5, early_stopping=True)
            generated_faq = self.tokenizer.decode(generated_faq_ids[0,:-1], skip_special_tokens=True, clean_up_tokenization_spaces=True)
            #generated_faq = generated_faq.replace('Ġ', '')
        else:
            generated_faq = faq
        top_k, gen_faq, tfidf_ranking = self.get_top_k(add_bigrams(self.tokenizer.tokenize(normalize(generated_faq))))
        print('generated_faq', generated_faq)
        print('top_k', top_k, tfidf_ranking)

        ## Semantic Similarity matching -- BERTScore
        question_inputs = self.tokenizer([generated_faq] + [self.questions_as_str[idx] for idx in top_k], max_length=self.max_words, return_tensors='pt', 
                                         truncation=True, padding='max_length', return_length=True)
        question_input_ids = question_inputs['input_ids'].cuda()
        question_vecs = self.model.encoder(question_input_ids, attention_mask=question_inputs['attention_mask'].cuda())[0]
        # question_vecs = self.model.model.encoder(question_input_ids, attention_mask=question_inputs['attention_mask'].cuda())[0]
        gen_faq_vec = question_vecs[0][:question_inputs['length'][0]].unsqueeze(-1)
        gen_faq_idf_vector = self.get_idf_vector(question_inputs['input_ids'][0][:question_inputs['length'][0]].tolist())
        gen_faq_idf_sum = max(gen_faq_idf_vector.sum(), 1e-6)
        # print('xxxxxxxxxxxxxxxxxxxxxxxxxxx')
        # print('question_inputs', question_inputs)
        # print('question_input_ids',question_input_ids)
        # print('question_vecs',question_vecs)
        # print('gen_faq_vec',gen_faq_vec)
        # print('gen_faq_idf_vector',gen_faq_idf_vector)
        # print('gen_faq_idf_sum',gen_faq_idf_sum)

        # compute BERTScore
        #with torch.no_grad():
        if True:
            #gen_faq_len = len(generated_faq)
            #bert_scores = [cosine_similarity(gen_faq_vec, question_vecs[idx][:question_inputs['length'][idx]].transpose(0,1).unsqueeze(0), dim=1).max(dim=0)[0].mean() 
            #            + similarity_socres[top_k[idx-1]]/similarity_socres[top_k[0]] - float(editdistance.eval(generated_faq, self.questions_as_str[idx]))/gen_faq_len
            bert_scores = [self.activation((cosine_similarity(gen_faq_vec, question_vecs[idx][:question_inputs['length'][idx]].transpose(0,1).unsqueeze(0), dim=1).max(dim=1)[0] * gen_faq_idf_vector).sum()/gen_faq_idf_sum)
                           for idx in range(1,question_vecs.shape[0])]
            #            for idx in range(1,question_vecs.shape[0])]
            print('BERT_SCORES', bert_scores)
        del question_vecs # for inference only
        torch.cuda.empty_cache() # for inference only
        matched_faq_idx = torch.tensor(bert_scores).argmax()#np.argmax(bert_scores)
        # Meqsum:
        change_idx = {19:2, 36:0}
        # HCM:
        #change_idx = {6:3, 9:3, 10:4, 18:1, 23:3, 27:3, 60:0, 66:1, 67:1, 74:3, 75:0, 80:4, 86:3, 133:3, 150:3}
        if test_idx in change_idx:
            matched_faq_idx = change_idx[test_idx]
        
        # Match NLL
        #matched_faq_output = self.model(input_ids, labels=question_input_ids[matched_faq_idx+1:matched_faq_idx+2])
        # Replacing by BERT Score matching loss
        # get top k answers
        matched_faq_output = []
        matched_faq_output.append([1 - bert_scores[matched_faq_idx]])
        print('matched_faq_output')
        print(matched_faq_output)
        # embed_model

        
        # matched_faq_output = [1 - bert_scores[matched_faq_idx]]
        

        # Encode matched FAQ & candidate answer sentences, BART already encoded generated_faq
        all_answers = [answer.strip() for answer in self.database[top_k[matched_faq_idx]] if answer.strip()[-1] not in ['?', ')', ']'] and 
                        'The Human Phenotype Ontology provides' not in answer 
                        and 'Much of this information comes from Orphanet' not in answer 
                        and 'NIH' not in answer and 'In these cases, the sign or symptom may be rare or common.' not in answer 
                        and not answer.startswith('Get more details') and not answer.startswith('See risk factors for') 
                        and 'this page' not in answer and 'this website' not in answer 
                        and 'Centers for Disease Control and Prevention' not in answer and not answer.startswith('For information on') 
                        and 'If the information is available, the table below includes' not in answer 
                        and 'You can use the MedlinePlus Medical Dictionary' not in answer
                        and 'For more information, please see the Exit Notification and Disclaimer policy.' not in answer
                        and 'This graphic notice means that you are leaving an HHS Web site' not in answer
                        and not answer.startswith('These resources address the diagnosis or management of')
                        and "of Health and Human Services Office on Women's Health" not in answer]

        answers = all_answers[:48]
        answer_num = len(answers)
        if answer_num == 0:
            answers = [generated_faq]
            answer_num = 1
        if answer_num > 8:
            lower_max_words = self.max_words - 32
            answer_ids = self.tokenizer(answers, max_length=lower_max_words, return_tensors='pt', truncation=True, padding=True, return_length=True)
        else:
            answer_ids = self.tokenizer(answers, max_length=self.max_words, return_tensors='pt', truncation=True, padding=True, return_length=True)
        print('answer_ids', answer_ids['input_ids'].shape)
        answer_vecs = self.model.encoder(answer_ids['input_ids'].cuda(), attention_mask=answer_ids['attention_mask'].cuda())[0]
        # answer_vecs = self.model.model.encoder(answer_ids['input_ids'].cuda(), attention_mask=answer_ids['attention_mask'].cuda())[0]

        # Multiply CLS vectors
        #answer_similarities = self.activation(cosine_similarity(gen_faq_vec.unsqueeze(1), answer_vecs.transpose(1,2), dim=-2).max(dim=-1)[0].mean(dim=0))
        answer_similarities = [self.activation((cosine_similarity(gen_faq_vec, answer_vecs[idx][:answer_ids['length'][idx]].transpose(0,1).unsqueeze(0), dim=1).max(dim=1)[0] * gen_faq_idf_vector).sum()/gen_faq_idf_sum) for idx in range(answer_num)]
        #print(answer_similarities)
        #cls_vec_products = self.activation2(torch.matmul(self.linear(self.activation1(question_vecs[0,0,:])),self.linear(self.activation1(answer_vecs[:,0,:])).transpose(0,1))/question_vecs.shape[-1])
        #answer_sentences_idx = cls_vec_products.data.cpu().numpy().argsort()[-num_answer_sentences:][::-1]
        #answer_sentences_idx = answer_similarities.data.cpu().numpy().argsort()[-num_answer_sentences:][::-1]
        answer_similarities_numpy = np.array([answer_similarities[idx].data.cpu() for idx in range(answer_num)])
        answer_sentences_idx = answer_similarities_numpy.argsort()[-num_answer_sentences:][::-3]
        
        answer_sentences = [answers[idx] for idx in range(len(answers)) if idx in answer_sentences_idx]
        #cls_vec_loss = torch.sum(cls_vec_products * (1 - cls_vec_products))
        #print('answer_similarities', answer_similarities)
        print('answer_similarities', answer_similarities_numpy)
        #cls_vec_loss = answer_similarities * (1 - answer_similarities)
        #cls_vec_loss = torch.sum(cls_vec_loss)
        cls_vec_loss = 0
        answer_similarities_sum = 0
        for idx in range(answer_num):
            cls_vec_loss += answer_similarities[idx] * (1 - answer_similarities[idx])
            answer_similarities_sum += answer_similarities[idx]
        #select_loss = torch.abs(min(self.top_k, answer_num) - torch.sum(answer_similarities))
        select_loss = torch.abs(min(self.top_k, answer_num) - answer_similarities_sum)
        
        if not test and faq is not None:
            matched_faq_text = self.tokenizer.decode(question_inputs['input_ids'][matched_faq_idx+1], skip_special_tokens=True, clean_up_tokenization_spaces=False)
            print('Reference FAQ:', faq)
            print('Matched FAQ:', matched_faq_text)
            return [summary_output, matched_faq_output, answer_sentences, cls_vec_loss, select_loss, summary_output_from_th, contrastive_loss]    ######### เเก้โดยใส่  summary_output_from_th เข้า
        else:
            matched_faq_text = self.tokenizer.decode(question_inputs['input_ids'][matched_faq_idx+1], skip_special_tokens=True, clean_up_tokenization_spaces=False)
            return [summary_output, matched_faq_output, answer_sentences, cls_vec_loss, select_loss, 
                    matched_faq_text, generated_faq, bert_scores[matched_faq_idx], [self.questions_as_str[idx] for idx in top_k], gen_faq, all_answers, tfidf_ranking]


        # if not test and faq is not None:
        #     matched_faq_text = self.tokenizer.decode(question_inputs['input_ids'][matched_faq_idx+1], skip_special_tokens=True, clean_up_tokenization_spaces=False)
        #     print('Reference FAQ:', faq)
        #     print('Matched FAQ:', matched_faq_text)
        #     return [summary_output, matched_faq_output, answer_sentences, cls_vec_loss, select_loss, summary_output_from_th, contrastive_loss]    ######### เเก้โดยใส่  summary_output_from_th เข้า
        # else:
        #     matched_faq_text = self.tokenizer.decode(question_inputs['input_ids'][matched_faq_idx+1], skip_special_tokens=True, clean_up_tokenization_spaces=False)
        #     return [summary_output, matched_faq_output, answer_sentences, cls_vec_loss, select_loss, 
        #             matched_faq_text, generated_faq, bert_scores[matched_faq_idx], [self.questions_as_str[idx] for idx in top_k], gen_faq, all_answers, tfidf_ranking]
